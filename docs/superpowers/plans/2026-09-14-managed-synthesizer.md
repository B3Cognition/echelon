# Managed Synthesizer integration

Approved in chat after the dependency ordering correction: preserve the normal
Discovery → Synthesizer → Modeler/Tracker → WHY1 workflow, integrating Synthesizer
before attempting review-triggered discovery repair. Execute inline with the
existing owners and test-first changes; independent read-only review is required.

## Goal and limits

Run Synthesizer against accepted discovery images, preserve existing U/A subjects
and revision-bound references, publish its seven required outputs and derived
graph, and recover its completion/checkpoint without rewriting discovery records.
No retirement, merge, replacement, provider-native agent lookup, external input
domains, live spending, installation or public/default activation is included.
AGENTS.md, CLAUDE.md, legacy build and the stopped smoke workspace remain untouched.

The existing internal selection remains discovery-only by default. An explicit
internal `through_phase: phase1-synthesizer` selects this additional checkpoint;
it is not a public rollout setting or permission for later producers.

## Implementation boundaries

- Retain Synthesizer selection, operation and provider markers under the existing
  protected Squad state owner, separately from original discovery and repairs.
- Reuse the proposal/reservation/author/review runner, secure receipt files,
  candidate preview, graph publisher and completion owner. Explicit closed
  producer selection determines paths/roles; old discovery encodings stay exact.
- Use a neutral synthesis producer body through Prosaic and the existing semantic
  reviewer. Both provider facades retain their no-tools inspection boundary.
- Capture accepted artifacts/context using the retained completion proof reader.
  Preserve the raw read set separately from the metadata-free identity baseline.
- Extend the existing checkpoint proof reader to append to an authenticated
  captured ledger preimage; never trust an arbitrary current ledger or omit it
  from source guards. The existing checkpoint writer still owns Git and ledger.
- Keep all existing definitions, subjects, captions and evidence revisions.
  Missing definitions, silent deduplication and unauthorized cross-owner edits
  reject before publication. New U/A use existing reservations only.

## Test-first execution checklist

- [x] Add normal-run acceptance using real discovery, state, SQLite, publication
  and Git, with scripted model/Prosaic boundaries. The run must reach the existing
  successor after synthesis, retain original discovery receipts, and not execute
  unsupported later producers. Run it against the baseline and observe failure.
- [x] Extend closed producer/assignment/state and receipt selection at existing
  owners. Cover altered source selection, injected state, missing receipts and
  immutable discovery history. No synthetic bootstrap/state view is permitted.
- [x] Wire synthesis capture, scoped candidates and Prosaic execution. Test
  ID removal/relabeling, semantic rejection, current evidence and source drift.
- [x] Integrate graph/publication/completion and second checkpoint with retained
  source proof. Exercise restart around provider response, publication, route,
  checkpoint, context, release and cleanup; no duplicate IDs, charges or effects.
- [x] Run both providers and guided/semi/banzai acceptance plus affected discovery,
  state, checkpoint and controller regressions. Review and fix concrete findings.
- [x] Record exact results and remaining Tracker/WHY1/repair work in the existing
  convergence records. Commit only the verified checkpoint, with no activation.

## Implementation and review notes

The initial normal-run acceptance failed against the discovery-only boundary.
The integration keeps old discovery assignment/recovery encodings unchanged;
only synthesis adds an explicit producer/source selection. The shared owners
retain their existing names and do not receive a fabricated bootstrap/state view.

Composition exposed two existing fresh-only assumptions: generated context
quotes accepted definitions, and the checkpoint projection previously admitted
only absent prior metadata. Synthesis now keeps actual generated context as
guarded evidence without parsing it as another canonical definition source, and
authenticates its captured ledger preimage before the existing writer appends.
Git artifact verification follows that writer's existing exclusion of its ledger
and lock; those bytes are checked separately, not silently ignored.

Independent read-only review identified two concrete P2 defects. An inherited
synthesis dispatch count could admit more work, and deleting the prior ledger
while the second checkpoint was pending could let the writer recreate it without
Discovery's row. Both were reproduced before fixing: admission now requires a
fresh synthesis count for a fresh operation, and append projection requires the
retained ledger to remain present. Re-review found no remaining concrete issue.

Recovery tests initially targeted the wrong context receipt function and passed
the checkpoint fault hook twice. These were test-harness errors, corrected to
interrupt the actual existing context installer and checkpoint writer. No
production fault hooks or duplicate completion implementation were introduced.
Final test review also tightened the cleanup interruption to require completed
synthesis, not merely the preceding Discovery's completed marker; otherwise it
could interrupt disposal of a provisional preparation instead of child cleanup.
The missing-receipt test initially expected the outer run tally to include
synthesis immediately after operation review. The existing contract retains
per-call usage first and charges the outer tally in the later routing/completion
transition. The corrected test checks those distinct records, explicit unknown usage after loss
of the selected turn receipt, and repeated fail-closed resume without new calls.
Independent read-only review confirmed that these assertions match the existing
accounting contract and do not conceal a lost or repeated charge.

## Verification record

- Existing discovery/state/publication/completion/checkpoint regression group:
  **684 passed in 640.41s**. This run began before the two final admission guards;
  the affected guards have separate targeted regressions and a later checkpoint
  compatibility rerun recorded below.
- Existing normal Squad controller integration group: **514 passed in 334.06s**.
- Two corrected second-checkpoint interruptions (`after_commit`, `after_ledger`):
  **2 passed in 50.95s**.
- New-subject synthesis reservation and replay: **1 passed in 23.99s**.
- Synthesis provider reply/accepted interruption: **2 passed in 31.80s**.
- Final checkpoint/semantic/candidate/turn/reservation compatibility rerun after
  both guards and import cleanup: **251 passed in 135.18s**.
- Broad synthesis acceptance batch: **32 passed, 4 failed in 733.20s**. Two failures
  used the already corrected duplicate checkpoint hook; two were the outer-usage
  expectation described above. The final affected rerun below supersedes those
  four failures and includes the strengthened cleanup/source-selection checks.
- Corrected child cleanup: **1 passed in 24.14s**. Active-state source selection
  and protected-record ownership: **1 passed in 23.23s**.
- Final affected acceptance rerun: **12 passed, 27 deselected in 241.61s**. This
  includes every corrected/strengthened test, all five second-checkpoint restart
  cases, new-subject allocation and provider-response restart. Together with the
  27 unchanged passing cases from the broad batch, all **39 distinct synthesis
  cases** are verified. This is reconciled batch evidence, not a claim that the
  earlier failing command was green.
- `git diff --check` passed. Independent production and final test/documentation
  review findings are resolved; no remaining concrete issue was reported.

All model and Prosaic subprocess boundaries are scripted. Filesystem, identity
SQLite, graph/publication, protected state, checkpoint Git and recovery owners
are real. These tests do not certify live provider output quality or installation.

## Handoff

Keep this as a local checkpoint on `fix/delivery-controller-contract`. Next is
the actual Modeler/Tracker continuation and WHY1 integration, then authenticated
review-origin repair and the original renumbering/evidence acceptance. No source
head reset, fake review, alternative allocator or checkpoint writer is permitted.
Full producer coverage and separately approved install/migration/live activation
remain open. The existing smoke workspace is unchanged.
