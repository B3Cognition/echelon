# Accepted discovery repair inputs implementation plan

> Use executing-plans inline and test-driven development. Independent read-only
> review is required; no implementation delegation.

**Goal:** Read an accepted discovery spec and generated context coherently for a
selected repair without weakening the fresh-discovery input guard.

**Architecture:** Reuse the retained completion proof and existing source
inspector. Authenticate exact graph/artifact/checkpoint images and context
receipt postimages; keep the complete raw capture as the read guard. This is
the source-admission part of repair execution, not review-origin authority or
permission to dispatch/publish a repair.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`.
Baseline `5eb87940`; reuse the approved retention and checkpoint extensions.

## Constraints

- Preserve exact IDs, immutable subjects, revision-sensitive evidence and history.
- No new controller, collector, allocator, provider role or publication owner.
- Existing runtime exclusions remain: external memory, RE, foreign features,
  extra context domains, product packages and retarget/polyrepo inputs block.
- No installation, migration, live spending, public activation, push or merge.
- Leave AGENTS.md, CLAUDE.md, legacy build and the stopped smoke workspace alone.

## Task: Coherent accepted input capture

Files: `discovery_completion.py`, `discovery_operation.py`, `squad_completion.py`
under `src/harness`; `tests/unit/test_discovery_repair_inputs.py`.

- [x] Add real normal-discovery → release → selected-repair capture tests, with
  and without a Git checkpoint. Require all six accepted discovery artifacts,
  retained graph in the full capture, and the authenticated generated context.
  Assert no provider call, attempt, receipt, canonical file or identity mutation.
  Run `pytest tests/unit/test_discovery_repair_inputs.py -q` and observe RED.
- [x] Extract the existing context receipt/image validation from its staged
  wrapper. The same closed schema, completion ID, digest and size checks apply
  to captured postimages after staging cleanup; do not recreate missing stages.
- [x] Extend the retained-proof reader to supply a checked spec projection and
  a checked runtime-context projection. Match the selected repair's source
  completion/digests exactly. Authenticate context membership, preimages,
  postimages and owner-produced modes before reusing original context only for
  the existing fresh-domain checks. Return current verified context to consumers.
- [x] Add `capture_discovery_repair_inputs(root, state_store, unit_id)` using the
  existing coherent `_capture` path and independently retained input-tree/scope.
  Admit the graph as an authenticated derived file, never an editable discovery
  artifact. Keep ordinary creation capture unchanged and full raw source images
  in the fingerprint. Caller retains execution leases and must still authenticate
  the requesting review before dispatch or publication.
- [x] Test modified/missing graph, context, metadata, foreign/runtime domains,
  stale repair-source binding, missing selection and mutation during inspection.
- [x] Run discovery inputs/operation/publication/completion/normal-entry/checkpoint/
  retention, Squad completion/source and context-builder regressions. Review,
  record evidence and commit the tested source-admission checkpoint.

## Runtime handoff still required

The current quality-review return edge exists in the workflow, but managed WHY1
and its preceding writers are not yet enabled. Do not manufacture an authoritative
review from the repair selection's string `review_id`, replay legacy writers,
or label a source-admission test as end-to-end repair acceptance. The following
execution connection must bind real requesting review occurrences, selected
repair provider receipts/budgets and guarded publication/completion/return routing.

## Verification and review

- RED: the two initial positive capture cases failed because the new capture
  entry point did not exist (**2 failed, 11 deselected in 8.96s**).
- The first implementation run passed 12 cases and exposed one fixture error:
  the foreign-knowledge test had not created its parent directory. Corrected
  that setup without changing production admission.
- Independent read-only review found no actionable correctness/security issues.
  Its nonblocking suggestions were added: direct v2 capture, insufficient v1
  proof rejection, missing repair selection and state mutation during inspection.
  Captures now explicitly hold the existing caller-owned execution leases.
- Final focused input capture suite: **17 passed in 89.78s**. This includes new
  v3 releases with/without checkpoints, retained v2 acceptance and v1 refusal
  without rewriting old proof, graph/context/checkpoint tampering, unsupported
  domains, missing/stale selection, deterministic replay, and file/state races.
- Publication/source inspection, source projection and execution-lock suites:
  **359 passed in 3.54s**.
- Delivery controller unit integration: **36 passed in 9.29s**.
- Complete Squad controller integration: **514 passed in 327.55s**.

- Combined discovery inputs/operation/publication/completion/normal-entry/
  checkpoint/retention, Squad completion/source snapshot/source guard and
  context-builder regressions: **677 passed in 617.16s**. This run collected the
  initial 13 repair-input cases; the final 17-case run above supersedes those
  cases and adds four. Across the selected suites: **1,590 distinct cases pass**.
- `git diff --check` is clean. No production edits followed independent review;
  its coverage suggestions changed only tests. No installed or live acceptance
  is claimed, and no provider, prose or activation configuration changed.
