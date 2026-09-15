# Identity work: convergence and deferred-scope record

## Status and purpose

Recorded on 2026-09-13 at implementation baseline
`4223b46ba27cb24503257879f08c4268c92dabed` on
`fix/delivery-controller-contract`, after merging upstream
`2c655b3d3c87aedcda2a08a8c89b5262f136a021`.
The pre-merge work is also retained by
`backup/delivery-controller-contract-before-upstream-20260913`
at `8581c06a1cb18ad6148861a0c9fcdc33a508646f`.

The user requested this record so deferred work can resume without inventing
a competing solution. This is a scope and decision handoff, not a new execution
plan or permission to continue implementation. The release dependency review
is recorded in the [convergence dependency boundary](element-identity-convergence-boundary.md).
No code has been removed,
extracted, enabled, or declared safe to remove by this record.

**Subsequent authorization:** the user approved implementing deferred components
when they are necessary dependencies of convergence, then requested continuation.
Record the reason and affected entry when taking up such work; do not repeatedly
request approval for the same necessary dependency. New capabilities, materially
different designs, or work beyond convergence still require stopping and asking.

The earlier [approved identity design](superpowers/specs/2026-09-12-durable-element-identities-design.md)
records the intended contracts and historical implementation checkpoints.
The later convergence direction narrows execution: preserve the work, determine
the release boundary, and prove complete workflows before expanding again.
Earlier design approval and checkpoint lists are not standing authorization
to finish every subsystem. Existing implementation is reusable work, not proof
that its whole architecture is required for the release.

## Work that is not being deferred by this record

- Original delivery work: harness-owned execution decisions, neutral role
  prose, and preserved banzai behavior without an additional orchestration layer.
- Stable identities across U/A/FR/NFR/AC/T/ISS producers, with at least six digits
  for new numeric labels and no application digit cap. Existing labels stay exact.
- Preventing the observed question reassignment/removal and evidence-reference
  corruption through an actual controller acceptance path, not only a validator.
- Candidate isolation, relevant semantic review, reference/history preservation,
  safe publication/recovery, and durable bounded discovery repair where required
  by that path. Safety dependencies cannot be deferred merely to reduce the diff.
- Offline end-to-end verification, followed by a separately approved, fresh,
  version-pinned live spec test with explicit spending and dispatch limits.

Normal producer allocation, positive managed acceptance/publication/completion,
and persistent targeted repair integration remain unfinished at this baseline.
They are release integration gaps, not completed features or optional polish.
Discovery is the first proving slice; it does not replace the remaining requested
entity families or authorize claims of complete coverage.

## Decisions to carry forward

These summarize existing contracts, not newly approved implementation choices.

1. **One allocation authority.** Use the workspace-owned SQLite identity ledger
   under `.echelon/identity/`, outside provider writes and ordinary spec rewind.
   Namespaces qualify workspace, canonical spec and type. Graphs, Markdown and
   providers do not allocate independently. Preserve retry reservations and gaps;
   never recycle IDs or reconstruct a lost established ledger from file maxima.
2. **Identity is not content.** Preserve immutable subjects and explicit revision
   history. A hash binds content; it does not establish semantic equivalence.
   New subjects require new IDs. Do not rewrite legacy labels into padded aliases.
3. **Evidence retains its meaning.** Bind verification to the assessed revision.
   New content does not inherit old proof. Distinguish a durable issue from its
   report occurrences; retain existing revision-sensitive resolution guards.
4. **One acceptance owner.** Integrate existing Squad publication and completion,
   not a parallel controller. Agents propose; the harness allocates, checks scope,
   routes review, publishes and recovers. Invalid candidates do not update accepted
   artifacts, identity history, graph or memory.
5. **Projections are consumers.** Preserve existing graph keys and historical
   bindings. Captured inputs, preview results and caller-supplied descriptors are
   not acceptance authority. A consumer that cannot preserve a requested lifecycle
   operation must block it, not drop history.
6. **Repair limits are durable.** Initial repair plus at most two automatic retries
   per selected repair unit, recorded before dispatch; unchanged failure stops
   early. Restart, reordered findings or new candidate hashes cannot reset the
   budget. All banzai modes obey the same identity-integrity rules.
7. **No silent migration or activation.** Independently writable clones are not a
   distributed counter service. Conflicting historical meanings require explicit
   reconciliation. Do not enroll a live spec while its supported execution and
   recovery paths remain incomplete.

## Deferred-capability register

The identifiers below are stable documentation keys, not runtime entity IDs.
Do not renumber or reuse them. Entries describe capability deferral, not a file
deletion list. The dependency boundary records which existing pieces must remain
available; necessary integration is authorized by the subsequent instruction above.

### DEFER-000001 — Broad lifecycle authoring

- **Preserve:** create/revise/retire and explicit replace/split/merge lineage;
  predecessors and their evidence remain historical entities.
- **Existing work:** [lifecycle model](../src/harness/element_identity_lifecycle.py),
  [lifecycle storage](../src/harness/element_identity_lifecycle_store.py), and the
  original design's entity-lifecycle contract.
- **Boundary:** general producer workflows for advanced lifecycle operations can
  wait if the release does not require them. Basic identity/revision preservation
  and any operation required by an accepted repair cannot be omitted.
- **Resume when:** a named authoring use case requires such an operation; prove
  semantic approval, lineage, evidence retention and all affected consumer behavior
  through publication before enabling it. Do not introduce a second lifecycle model.

### DEFER-000002 — Broader graph and memory history capabilities

- **Preserve:** qualified stable keys, revision/lifecycle metadata, predecessor
  links and captured-source provenance; projections are not a second ledger.
- **Existing work:** [history snapshot](../src/harness/element_identity_snapshot.py),
  [graph identity integration](../src/echelon/spec_graph_identity.py), and captured
  graph/memory composition checkpoints in the original design and storage guide.
- **Boundary:** broader historical traversal and multi-domain projection activation
  are candidates for deferral. Existing affected graph/memory consumers still need
  compatibility and integrity protection for every release-supported operation.
- **Resume when:** a concrete consumer needs historical behavior. Reuse its existing
  authority/adapter, verify the complete source/configuration read set and recovery,
  and retain `MemPalaceContext` as the existing wing-context owner. Separate captures
  or supplied source descriptors do not establish one coherent accepted snapshot.

### DEFER-000003 — Operator tooling and historical migration

- **Preserve:** workspace identity/epoch, exact legacy labels, reservations,
  revisions and receipts in audit/export/restore; conflicts block, not auto-merge.
- **Existing work:** [standalone identity administration](../src/harness/element_identity_admin.py)
  and [storage guide](element-identity-storage.md).
- **Boundary:** broad CLI exposure and adoption of existing conflicted workspaces
  can wait. Required initialization, integrity checks and recovery for the selected
  fresh-spec release path cannot be postponed under this entry.
- **Resume when:** migration or operator recovery is explicitly requested. Inspect
  existing commands and schemas first; require a reconciliation report for ambiguous
  history and test restoration of the full authority, not just current documents.
  Do not reinterpret this as a request for distributed allocation.

### DEFER-000004 — Broader managed ownership and publication rollout

- **Preserve:** durable publication intents/receipts, authenticated staged inputs,
  accepted before-images, exclusion of conflicting writes and idempotent recovery.
- **Existing work:** [managed ownership](../src/harness/element_identity_managed_store.py),
  [publication ledger](../src/harness/element_identity_publication_store.py),
  [sealed publisher](../src/harness/squad_publication.py), and
  [completion owner](../src/harness/squad_completion.py).
- **Boundary:** rollout beyond the tested release path can wait. Publication safety
  and recovery needed by that path cannot. Some legacy/projection exclusion guards
  are already wired on this branch: the subsystem is not wholly dormant. Enrollment
  can block legacy execution without a completed positive managed replacement.
- **Resume when:** the requested path has producer, review, publication, completion
  and crash-recovery tests. Cover both immediate completion and pending-completion
  recovery; preserve recovery material until dependent effects are safe. Do not
  solve enrollment failures by bypassing the guards or adding another publisher.

### DEFER-000005 — Generalized candidate/provenance expansion

- **Preserve:** explicit typed artifact roles, exact before/after bytes, controller
  edit scope, source-bound references and distinction between structural validation
  and semantic approval. Projections and issue occurrences are not new definitions.
- **Existing work:** [candidate contract](element-identity-candidates.md),
  [candidate source assembly](../src/harness/element_identity_candidate_sources.py),
  and [coherent preview](../src/harness/element_identity_candidate_preview.py).
- **Boundary:** new formats, extra source domains and generalized preview APIs can
  wait. The complete artifact/dependency set required by each selected producer and
  its evidence/reference validation remains necessary.
- **Resume when:** a named unsupported artifact or consumer requires expansion.
  Extend the existing adapter/composition boundary and test real captured inputs;
  do not infer roles from filenames or treat preview success as publication approval.

## Open choices: do not mistake these for settled design

On 2026-09-14 the user approved a discovery-first integration approach after
controlled-fulfillment closure. The
[managed discovery design](superpowers/specs/2026-09-14-managed-discovery-integration-design.md)
records the producer/reservation/review contract, subsequently approved by the
user. Its first inactive semantic/translation checkpoint is implemented in the
[executed plan](superpowers/plans/2026-09-14-discovery-producer-contracts.md), with
551 affected tests passing and a clean independent review.
It reuses the necessary parts of DEFER-000002/000003/000004/000005 and only
create/revise from DEFER-000001. No capability is activated by this record;
public activation and the other producer families remain subsequent checkpoints.

The producer wire shapes are now explicit: proposal handles stay out of authored
Markdown, and the author uses supplied reserved IDs. The inactive
[reservation-binding checkpoint](superpowers/plans/2026-09-14-discovery-reservation-binding.md)
now retains canonical proposals, exact per-kind intents and key/subject/ID
associations across allocation interruptions and subsequent proposals. It uses
the existing allocator plus a read-only retained-reservation lookup, not another
identity authority. Its 613 affected tests passed with no independent review
findings. Already registered genesis/source context is authenticated. The next
[inactive bootstrap checkpoint](superpowers/plans/2026-09-14-discovery-bootstrap.md)
now connects protected selection/capture/completion transitions in the existing
SquadStateStore to the existing source/genesis registration APIs. Explicit resume
requires matching state and retained authority, and pending bootstrap blocks
legacy Squad entry before enrollment. Final acceptance passed 848 affected tests
plus 397 managed/Squad exclusion regressions. Review found a completion-before-
source-exit-validation ordering defect; two RED regressions preceded its fix,
and no review findings remain. Existing execution leases are caller-owned;
positive Squad admission and full provider-input/domain selection still require
runtime integration. This is not a new storage authority or public activation.
The [inactive provider recovery checkpoint](superpowers/plans/2026-09-14-discovery-provider-recovery.md)
now binds individual semantic steps to neutral Prosaic roles, provider configuration,
bootstrap authority, inputs and read policy. A protected state marker prevents
missing receipts from resetting the operation. Pending calls, validated replies,
host reads and checked final results have separate durable boundaries; unknown
completion blocks, completed results replay and budgets only tighten. Shared
secure file mechanics were extracted from the reservation journal without changing
its schema or allocator behavior. No additional deferred capability is activated.

The [reviewed-candidate checkpoint](superpowers/plans/2026-09-14-discovery-reviewed-candidate.md)
now orders proposal/reservation/author/preview/review for one selected operation,
captures its explicit input/spec/template selection and consumes each of at most
three attempts through protected Squad state. Exact candidate/source citations,
permanent proposal associations and normalized no-progress checks constrain
rejection/retry. Offline tests prove U/A creation and proposed same-subject revision
without changing accepted artifacts/history. The affected batch passed 1,734
tests, with 41 composition cases additionally rerun under actual execution leases.

Runtime wiring remains a gap: the caller must establish all configured inputs and
dependency domains, then authenticate the reviewed candidate at publication and
the existing Squad completion owner. The helper does not select subsequent accepted
repair units, expose a public mode or activate unsupported sources/producers.
Missing selected journals deliberately require reconciliation; do not replace that
boundary with automatic reset. The full original renumbering/evidence fixture and
actual provider-facade/mode acceptance remain runtime duties.
The [runtime-input checkpoint](superpowers/plans/2026-09-14-discovery-runtime-inputs.md)
now makes fixed local runtime capture and domain exclusion mandatory inside that
operation. It binds config, optional constitution, existing generated context,
knowledge/evolution documents and selected semantic run state. Actual memory-wing
configuration, RE-root presence and run selection are checked; supplied empty
observations alone cannot admit a linked domain. Existing RE roots, configured
memory, prior/WIP feature context, additional context domains, structured product
packages and polyrepo/retarget selections remain explicitly unadmitted here.
Do not turn these exclusions into a new public mode, clear configured wings,
regenerate missing context, or reset old operation fingerprints to pass them.
An empty feature registry does not authenticate the text beside it. Newly
captured runtime documents with parsed identity references or diagnostics block
until their provenance can be admitted; they must not bind foreign IDs to new
same-spelled allocations. Keep the existing explicit spec-scoped input-tree
contract separate from these additional runtime domains.
Typed evidence/investigation selection and guarded Squad publication/completion
are still the next required integration work, not a new collector implementation.
The [publication preparation checkpoint](superpowers/plans/2026-09-14-discovery-publication-preparation.md)
now seals an accepted discovery candidate and its graph through the existing
publication owner. Replay-only requires completed provider and reservation
receipts; preparation cannot reconstruct missing records or consume another
attempt. The v3 request retains a spec-only registered identity baseline and the
complete runtime read set separately. Preserve both scopes: never widen genesis
or use the smaller baseline as the publication guard. The supplied completion ID
and returned recovery document are proposed association data, not durable Squad
authority. Unbound staging is retryable; pending publications cannot be reselected.
No canonical promotion, identity application, source-head advance, completion,
positive Squad admission or rollout occurs in this production helper. Those
connections remain required next work at the existing owners, including recovery
before the next unsupported producer and admission of an existing derived graph
when selecting a subsequent accepted repair. Do not mistake the fixture-only
guarded publication test for that runtime integration.
The [completion-binding checkpoint](superpowers/plans/2026-09-14-discovery-completion-binding.md)
now associates the retained reviewed package with the existing Squad completion
owner. Guarded publication prepares/applies the exact identity intent; completion
effects finish before identity release and stage cleanup, with restart using the
existing dispatch/completion receipts. Keep the full read guard separate from the
registered spec-only source claim. The approved captured-input context-builder
path renders selected reviewed postimages only; it must not reopen live workspace
discovery, external collection or foreign feature admission. Receipt preimages
remain tied to the reviewed context and postimages remain checked through release.
Positive managed Squad entry, subsequent accepted repair selection, the full
renumbering/evidence acceptance and actual provider-facade/mode acceptance remain
open. Do not infer rollout or unsupported next-phase authority from completion
success. Seven old Squad integration assertions still expect managed legacy
dispatch; they reproduce on the prior checkpoint and need separate reconciliation
with the existing negative guard, not removal of that guard.

The provider recovery plan records exact verification and review receipts;
exact public activation configuration still requires an integration decision. Reuse existing
capabilities, but do not claim that storage APIs alone settle these interfaces.
The final code extraction boundary and which deferred components remain necessary
dependencies also remain open. Record the decision before implementation; do not
silently create a competing protocol or declare the entire backlog mandatory.

## Resume and change protocol

Normal-entry work and the checkpoint/source interaction
are recorded in [the normal-entry plan](superpowers/plans/2026-09-14-discovery-normal-entry.md).
The user-approved checkpoint extension keeps the existing Git flow and ledger
location. Fresh-discovery metadata is authenticated against exact Git artifact
images and the completion receipt; the existing identity release payload retains
the proof. Later spec-source/repair capture must use its checked identity projection
while retaining the complete capture for read guards. This does not activate repair
or cover later checkpoints over an existing ledger: those must extend the existing
owner with authenticated preimages. Do not disable checkpoints, ignore the entire
control directory, invent a second ledger, or rewrite managed source heads without
publication authority.

The subsequent approved [repair retention extension](superpowers/plans/2026-09-14-discovery-repair-retention.md)
supersedes the earlier choice to retain only minimal proof for new no-checkpoint
releases. New releases retain full version-3 proof in the same identity row;
already released version-1/version-2 payloads remain byte-for-byte unchanged.
Version 1 remains insufficient for positive repair admission. Repair association
and attempts are protected separately by Squad state, and the existing secure
receipt files have strict per-unit namespaces; no original record is rotated.
These are retention/selection prerequisites, not authenticated report provenance
or a completed repair execution path. The subsequent runtime work must reuse
them and must not reset the original operation or repair budgets.

The [accepted repair input checkpoint](superpowers/plans/2026-09-14-discovery-repair-inputs.md)
now reuses that retained proof and the existing source inspector. Checked spec
and context projections are for admission only: consumers receive current
receipt-verified context, and the complete raw tree remains the freshness guard.
Do not replace this with graph omission, live context regeneration or a general
exception allowing IDs in arbitrary runtime inputs. Requesting-review provenance,
per-unit execution and guarded repair publication/return are still unimplemented;
the opaque selected `review_id` must not become their authority by assumption.

The approved [managed Synthesizer checkpoint](superpowers/plans/2026-09-14-managed-synthesizer.md)
follows the real workflow ordering before review-triggered discovery repair.
It reuses the existing owners with closed producer selection, separate immutable
discovery/synthesis records, retained parent completion proof and an authenticated
second-checkpoint ledger append. This supersedes the earlier fresh-ledger-only
limitation for this specific managed continuation, not for arbitrary existing
ledgers. Exact raw metadata/context remain guarded; derived context is evidence,
not a second canonical definition source. Default selection stays discovery-only.
Modeler/Tracker and WHY1, followed by authenticated review-origin repair and its
original renumbering/evidence acceptance, remain required convergence work.
Do not skip these producers or fake a requesting review to demonstrate repair.
Installation, migration and live acceptance remain separate approval boundaries.

The approved [intent identity prerequisite](superpowers/plans/2026-09-14-intent-identities.md)
now admits UI/II through the existing allocator, lifecycle, candidate/history and
graph owners. Reuse this contract when integrating Tracker: author from exact
reservations, preserve existing labels/subjects and revision-bound evidence, and
classify its two native intent tables with the explicit `intent` role. Table
headers and surrounding prose still require the existing unowned-text permission.
Do not invent Tracker-local counters, rewrite old three-digit labels, substitute
headings for table definitions, or silently adopt existing UI/II prose. The shared
reference lexer now recognizes these families; unsupported or unregistered legacy
mentions must be reconciled explicitly. Older binaries cannot read populated UI/II
registries; no mixed-version rollout readiness is claimed.

Managed Tracker execution is still pending, including native ALIGNED/DRIFT/
STOP_AND_ASK routing through the existing human-input owner, exact producer input
proof and publication/checkpoint continuation. The current managed domain is
greenfield, whose native workflow skips Modeler; do not expand to brownfield just
to exercise Modeler. Keep WHY1 and review-origin repair/return integration, then
the original renumbering/evidence acceptance, as subsequent checkpoints. This
prerequisite does not activate a producer or authorize a live trial.

The [managed Tracker plan](superpowers/plans/2026-09-15-managed-tracker.md) now records
the approved clarification/re-entry extension. Its first checkpoint is detached
candidate preparation: reuse `prepare_clarification_candidate` and the extracted
existing reconciliation renderer. Do not reimplement policy inference or derive
past decisions by parsing the rendered Markdown receipt. Its `previous` records
must come from authenticated human-input history, with exact receipt/policy
preimages guarded by the publisher. The helper alone grants no decision/source
authority and does not safely replace the current resolver on its own.

Next integrate guarded clarification publication and separate immutable Tracker
rounds, then normal provider dispatch/verdict routing. Stage context from captured
projected inputs using the existing completion owner; do not call the legacy
resolver's live context regeneration on a managed run. Existing requirement
content is preserved by reconciliation: the legacy mutation is the report write,
not a rewrite of the original requirements. Keep all current managed-exclusion
guards until a specific admitted path proves source, decision and recovery
ownership. The initial two provider acceptance tests remain intentionally RED and
uncommitted until that path reaches WHY1 without executing it.

For the next producer's input admission, reuse the extended retained completion
reader's full context-ancestry projection. The prior one-hop rollback left
Discovery's generated identity references in the admission context after Synthesis.
The partial Task 2 fix authenticates both retained generations and the exact
parent artifact/history/context links; current raw captures and model evidence
remain unchanged. Extend this same owner for future Tracker/clarification bindings
and exact historical round selection. Do not bypass domain admission, erase
generated context, reconstruct an earlier state by editing current producer keys,
or invent another ancestry ledger. This prerequisite is not guarded answer/resume
or a passing Tracker run; those tasks remain approved and open.

Reuse the now-defined Tracker version-3 semantic/candidate contract when wiring
that execution. Review assignments bind the exact authored routing object;
carry it through candidate hashes, persisted turn decoding and completion proof,
not just the transient reply. Old Discovery/Synthesis encodings remain exact.
An optional stakeholder `null` preserves absence and cannot delete an existing
file: retain its raw source guard while omitting absent candidate/write paths.
UI/II statement revisions use the existing immutable registry subject and exact
ID; no new allocator or caption-as-subject identity rule is introduced. This
inactive Task 3 dependency does not complete Task 2: round/state/receipt owners,
guarded human resolution and normal Tracker execution still need integration.

The existing receipt owners now support exact v3 recovery and explicit Tracker
`round_operation_id` namespaces. Reuse these paths; do not introduce flat active
Tracker journals or replace prior round files. The namespace is not authority:
the protected state owner still needs to derive/bind it to the accepted parent
completion and resolved decision, and historical readers must select that exact
round. Existing allocator receipts recover interrupted UI/II mappings without
new allocations. Run-level cumulative accounting and missing-selected-journal
guards still require integration; passing low-level journal tests do not imply
that Tracker re-entry or controller dispatch is enabled.

**Tracker disposition, 2026-09-15: completed for the approved managed greenfield
boundary.** This supersedes the pending Tracker paragraphs above, retaining them
as prerequisite history. See the [completed plan](superpowers/plans/2026-09-15-managed-tracker.md)
for exact verification and review evidence. Internal selection now reaches WHY1
through native Modeler skip and Tracker; default/public activation is unchanged.

On resumption, reuse the connected `managed_tracker_rounds` predecessor chain,
round-local existing journals, v4 Tracker and v5 human clarification completion
proof, and the existing human-resolution CAS/publication/release owners. The
human receipt remains distinct from its parent `last_dispatch`. Authenticate the
exact parent operation/STOP decision and all three staging postimages, including
absence, before deriving next-round inputs. Do not replace this with Markdown
decision parsing, a second ledger, flat active journals or resettable counters.
Clarification can derive WHAT from the existing reconciliation report; that route
does not authorize repair execution. Existing automatic-answer eligibility and
phase caps remain authoritative. Codex/Claude share neutral Prosaic roles.

Tracker is no longer a deferred integration item. WHY1 and authenticated
review-origin repair/return, then the original renumbering/evidence acceptance,
remain subsequent convergence work. Brownfield expansion, installation, migration
and live-provider acceptance remain outside this completed boundary. Do not
reimplement the completed Tracker seams when continuing those items.

**WHY1 disposition, 2026-09-15: completed for the approved managed greenfield
review boundary.** This supersedes the pending WHY1 references above without
erasing prerequisite history. See the [completed WHY1 plan](superpowers/plans/2026-09-15-managed-why1.md)
for 44 passing partitioned acceptance cases, affected regression results and
independent review evidence. Internal selection executes WHY1 and stops at its
native destination; public/default selection and installation remain unchanged.

Reuse the existing `managed_why1_rounds` protected predecessor chain, exact
round-local journals, v4 semantic assignments and v6/v7 completion bindings.
The first parent is accepted Tracker; later rounds require the exact resolved
WHY1 decision and existing human receipt. Keep Tracker and earlier WHY1
clarifications in authenticated ancestry, not mutable copies or parsed Markdown.
Existing automatic-answer eligibility, iterative dispatch caps and cumulative
usage accounting remain authoritative. Codex/Claude share neutral Prosaic roles.

WHY1 publishes findings, not upstream repairs. Existing assumptions and unknown
definitions are read-only; justified U/ISS additions use the existing allocator
and stable six-digit-minimum IDs with no application width cap. Reuse native
issue-report contexts and exact historical occurrence revisions, not current
head revisions substituted for old evidence. The captured reasoning journal is
read-only evidence, not another decision ledger. Preserve before-publication
source/journal guards and after-release immutable database completion authority.

Next integrate authenticated review-origin repair/return; initial Discovery
completion must never be replayed as repair. Preserve native FAIL/BLOCKED
iteration/forced-convergence routing and the explicit unsupported-repair guard
until that admission is verified. Constitution execution, subsequent managed
continuation, original renumbering/evidence acceptance and rollout remain open.
WHY1's report PASS is not proof that downstream work ran or activation occurred.
Do not broaden into brownfield, change legacy build, add provider-native prose,
or replace these completed owners when resuming the next boundary.

**WHY1 repair admission checkpoint, 2026-09-15: completed for the approved
selection-only boundary.** The convergence record contains exact evidence:
25 passing new cases in partitioned runs and 385 affected regression cases,
with independent review findings fixed before completion. This does not change
the open disposition of repair execution/return or activate another producer.

Reuse `prepare_why1_discovery_repair` inside native managed admission under its
existing execution leases. The retained completion reader authenticates the
actual WHY1→Discovery route; current phase text, supplied review IDs and Markdown
alone are not authority. The captured accepted source is the latest WHY1 head,
not the initial Discovery completion. Preserve the existing source/context
projection and exact review input comparisons when connecting execution.

Repair findings use the existing selection's `key`/`detail` records to retain
the complete native issue occurrence and exact reviewed target revision, source
digest and content digest. Keys are deterministic association hashes, not new
element IDs or counters. Current admission requires a single unambiguous retained
report identity and current active ISS revision, even though historical display
still supports old occurrences. Do not select the first equal-text historical
report or transfer its evidence to the current issue head. Native-visible SAGE
metadata identifies one existing U/A target per actionable issue; unsupported
scope must stop, not silently widen to whole files or another owner.

The existing repair-state shape, per-origin budget identity and three-attempt
ceiling remain unchanged. Selection uses the owner's full-state comparison and
does not begin an attempt. Future dispatch must reauthenticate source/origin and
use the selected unit's existing isolated journals; the stored association alone
is not permission. The older discovery-only repair input helper is not proof
that execution can consume the post-WHY1 artifact set. Connect its read-only
downstream context through existing capture owners, without replaying or replacing
the accepted initial Discovery/Synthesis/Tracker/WHY1 records. Keep the unsupported
repair guard until that execution/publication boundary is independently verified.

**WHY1 repair execution checkpoint, 2026-09-15: checkpoint 2 completed.**
The user approved optional execution metadata on selected units. This explicitly
supersedes the selection-only shape and unsupported-execution statements above;
it does not replace selection identity, scope or the existing attempt ledger.
See the [execution plan](superpowers/plans/2026-09-15-discovery-repair-execution.md)
for verification and independent review evidence: all 17 current execution cases
and 562 distinct affected regression cases passed in offline partitions.

Reuse the selected unit's immutable binding/turn marker and existing attempts,
the shared Discovery operation with explicit `repair_unit`, isolated receipts,
and v8 completion proof. Old units and old completion encodings remain valid.
The actual WHY1 FAIL route and native findings are reauthenticated from retained
inputs during recovery. A stored selection alone, edited phase state or an
unreviewed Discovery completion cannot authorize repair publication. Scope is
selected existing U/A revisions only; reject additions and omissions before
allocation. Do not introduce another allocator, attempt ledger, repair controller
or provider-native role. Count a unit's first execution once; restart cannot
reset dispatch, attempt, progress or token accounting.

Publication now returns to WHY1 but deliberately guards dependency refresh and
re-review. Checkpoint 3 remains open: derive affected dependencies from the exact
published repair, preserve historical inputs/receipts/issue occurrences and
re-enter the requesting review through existing owners. Do not lift the guard
by replaying the original Discovery, Synthesis, Tracker or WHY1 records against
new inputs. This checkpoint does not complete downstream continuation, original
renumbering/evidence acceptance, installation or activation. Keep the original
stopped browser-game workspace unchanged; live acceptance is not implied.

1. Read this record, the linked original contract, and only the implementation
   checkpoints relevant to the selected entry. Inspect current upstream and callers;
   these commit references are a baseline, not a claim about future code.
2. State the requested user-visible outcome and whether this is required release
   integration or an explicitly resumed deferred capability. Name the entry and
   proposed dependency boundary. Necessary convergence dependencies are approved;
   obtain approval before adding capabilities or materially changing the design.
3. Reuse the existing owner and contract. If new evidence makes the earlier decision
   unsuitable, document what changed, the replacement, compatibility/migration cost
   and user approval. Supersede decisions explicitly; do not erase their rationale.
4. Add an end-to-end acceptance case and failure/recovery checks for the selected
   path. Foundation tests alone do not demonstrate integration or safe rollout.
5. Update this same entry with its disposition, decision/commit references and exact
   verification evidence. Keep completed/superseded entries rather than renumbering.

Keep the original stopped browser-game smoke workspace unchanged. Any future
live trial requires separate approval and matching Python/deployed bundles.
This documentation update does not authorize installation, migration, provider
spending, branch extraction, merge to main or activation.
