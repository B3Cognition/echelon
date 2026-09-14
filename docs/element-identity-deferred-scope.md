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
records the proposed producer/reservation/review contract for written review.
It reuses the necessary parts of DEFER-000002/000003/000004/000005 and only
create/revise from DEFER-000001. No capability is activated by this record;
public activation and the other producer families remain subsequent checkpoints.

The producer proposal/reservation wire format, candidate placeholder convention,
binding of proposals to reservation requests, semantic-review handoff, and exact
activation configuration still require an integration decision. Reuse existing
capabilities, but do not claim that storage APIs alone settle these interfaces.
The final code extraction boundary and which deferred components remain necessary
dependencies also remain open. Record the decision before implementation; do not
silently create a competing protocol or declare the entire backlog mandatory.

## Resume and change protocol

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
