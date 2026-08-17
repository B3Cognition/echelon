# Git-First Candidate Restore and Certification Integrity

Date: 2026-08-14
Status: approved in conversation; written review pending
Parent design: `docs/superpowers/specs/2026-08-13-proportional-spec-repair-loop-design.md`

## Problem

The proportional repair branch correctly bounds repair accounting and records
candidate authority, but repeated file-first restore fixes still leave race and
recovery gaps. The worktree is currently mutated before the authoritative
restore checkpoint exists. This makes correctness depend on path classification,
exchange-temporary cleanup, later staging, and a final checkpoint window.

The final review also found two adjacent authority gaps:

- combined candidate capture may mutate Git and run artifacts before the older
  selected manifest is fully authenticated; and
- ordinary certification can proceed when the provider envelope and numeric
  report say PASS but the authoritative SAGE issues artifact says FAIL.

## Decision

Candidate restoration becomes Git-first. Echelon will construct and verify the
complete target restore commit before modifying the worktree. That immutable
commit, rather than a collection of path observations, becomes the recovery
authority. Worktree materialization converges to the commit and never creates a
new checkpoint by staging the mutable worktree.

Manifest preflight and SAGE certification are tightened in the same change
because both determine whether the restore/debt transaction is valid before its
first side effect.

## Invariants

1. Every persisted candidate slot is loaded once through a pinned, no-follow
   regular-file snapshot and must contain the candidate ID named by its path.
2. Ranking, recommendation, selected evidence, and restore authority use the
   parsed content and SHA-256 from that same snapshot.
3. All candidate and selected-manifest authority is validated before creating a
   candidate checkpoint, restore commit, journal, or worktree mutation.
4. The target restore commit contains the selected checkpoint's exact blob ID
   and Git mode for every owned artifact.
5. Unowned paths and their tree entries are inherited unchanged from the sealed
   base checkpoint.
6. No restore path uses `git add -A` or derives the checkpoint from mutable
   worktree bytes.
7. Restore retry accepts only a sealed base image, the exact target image, or a
   documented journal transition between them. Unrelated drift fails closed.
8. A completion receipt is written only after the target ref and every owned
   worktree path match the target commit.
9. Ordinary certification requires numeric Understanding PASS, provider PASS,
   and authoritative SAGE PASS. A SAGE FAIL never becomes an ordinary passing
   certificate.
10. Eligible non-critical SAGE FAIL may continue only through the explicit,
    content-bound quality-debt decision path.

## Manifest Authority Preflight

Decision preparation opens each `<candidate-id>.json` through a pinned parent
directory and `O_NOFOLLOW`, verifies regular-file identity before and after the
read, parses strict schema, and requires `manifest.candidate_id` to equal the
candidate-list slot. The loader returns an immutable pair of parsed manifest and
digest of those exact bytes.

Before any combined candidate-capture/restore effect performs a side effect, it
prevalidates:

- the current candidate manifest inputs to be written;
- every persisted candidate snapshot used for ranking/history;
- the selected snapshot's candidate ID and digest;
- the selected checkpoint and its owned path tree entries; and
- the sealed base checkpoint/ref expected by the transaction.

A replacement after preflight is detected by the effect-time digest check and
fails before mutation. A swapped candidate-list slot is rejected during
preflight.

## Constructing the Restore Commit

The controller uses Git plumbing with an isolated temporary index under the
run artifact directory:

1. Read the sealed base checkpoint tree into the isolated index.
2. Read the selected candidate checkpoint's exact `(mode, blob-id, path)` entry
   for each owned artifact.
3. Update only those owned entries in the isolated index.
4. Write the target tree and create a deterministic restore commit whose parent
   is the sealed base checkpoint and whose trailers identify the run,
   completion, selected candidate, and restore action.
5. Verify the commit tree: every owned entry must equal the selected checkpoint
   mode and blob ID; every unowned entry must equal the base tree.

Creating Git objects is idempotent and does not mutate the worktree or active
ref. The target commit hash and exact tree-entry map are persisted in the
controller-owned restore journal before materialization.

## Worktree Materialization and Journal

The journal lives under the run artifact root, outside publication and
checkpoint pathspecs. It binds:

- schema version and completion ID;
- sealed base ref/commit and target restore commit;
- selected candidate ID and manifest digest;
- every owned path's base and target blob IDs and modes;
- deterministic temporary paths; and
- transaction state.

For each owned artifact, Echelon materializes the target blob into a
file-synced deterministic temporary file under the journal directory. The final
component in the worktree is read through a pinned directory descriptor with
no-follow semantics. It must match either the sealed base entry or exact target
entry, including mode.

When replacement is needed, Echelon uses the existing platform atomic-exchange
primitive between the worktree entry and the deterministic journal temporary
on the same filesystem. The displaced base entry therefore remains outside the
checkpoint pathspec. The journal records and fsyncs transition intent before
exchange; retry classifies both entries by pinned identity, blob digest, and
mode, then completes exchange or cleanup deterministically. Unknown residue,
symlinks, directories, mode drift, or content drift fail closed.

After all owned entries match the target, Echelon:

1. verifies them again through pinned descriptors;
2. atomically updates the active checkpoint ref from the sealed base commit to
   the already-verified target restore commit using compare-and-swap;
3. verifies the ref and owned worktree entries against the target commit again;
4. removes and fsyncs journal material; and
5. writes the outbox effect receipt.

A crash before ref update leaves either base, target, or a journaled exchange
state and is recoverable. A crash after ref update is recovered by treating the
target commit as authority and reconciling the worktree before receipt. No
worktree staging occurs at any point.

## SAGE Certification and Debt Boundary

Candidate capture derives one authoritative assessment state from:

- deterministic Understanding result;
- provider envelope verdict; and
- authoritative SAGE issues verdict plus issue ledger.

Ordinary PASS requires all three to pass. Any authoritative CRITICAL issue,
contradiction, evidence gap, product-input blocker, or other hard structural
contract remains terminal/ineligible regardless of numeric scores.

A non-critical SAGE FAIL with complete unique `spec_repair` routes is a
qualitative proportional failure. It may be repaired or explicitly accepted as
quality debt. Qualitative-only debt has `failed_gates: []` and a nonempty,
content-bound qualitative issue list; it never fabricates numeric failure and
never creates a passing certificate. Missing, extra, duplicate, empty, or
non-repair routes prevent the decision from being sealed.

Provider/SAGE PASS with a contradictory authoritative FAIL artifact is rejected
as an integrity mismatch rather than certified.

## Recovery and Compatibility

- Existing completed candidate and debt state remains readable.
- Pending pre-Git-first restore effects are not guessed into the new protocol.
  They either complete through their exact legacy handler when safely
  classifiable or fail closed with explicit recovery guidance.
- Current completion-outbox schema-v1 compatibility and original digest
  authority remain unchanged.
- Perfectionist routing and its global iteration safeguard are unchanged.
- The passing-certificate format and quality-debt schema remain unchanged except
  for the already-supported qualitative-only debt shape.

## Testing

Production-path tests will prove:

- selected executable/non-executable Git modes are restored exactly;
- regular-to-symlink and same-digest inode/mode swaps fail closed;
- crashes before exchange, after exchange, before ref update, and after ref
  update recover to one target commit and one receipt;
- deterministic journal residue is never staged and unexplained residue is
  rejected;
- the final ref, commit tree, and worktree all match exact target blobs/modes;
- candidate-list swaps and rank-to-seal replacement fail before any Git or run
  artifact mutation;
- numeric PASS plus SAGE FAIL cannot certify;
- eligible qualitative FAIL reaches executable guided and banzai debt choices;
- hard blockers and incomplete routes remain fail closed;
- ordinary numeric/SAGE PASS, qualitative debt, legacy outbox recovery, and
  perfectionist behavior retain their existing contracts.

Focused controller, checkpoint, outbox, candidate, debt, publication, CLI, and
summary suites will run before the expanded feature suite, `tests/run-all.sh`,
package/deployment checks, bundle checks, and full pytest.

## Non-Goals

- Fixing the deferred Tasks Lexicon recovery-command defect.
- Fixing the deferred false publication claim in the terminal summary.
- Redesigning generic Git checkpoint creation outside candidate restoration.
- Changing repair budgets, thresholds, autonomy modes, or sealed decision
  options.
