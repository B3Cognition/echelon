# Proposal: `echelon spec amend`

**Status:** Proposed
**Date:** 2026-07-23
**Decision owners:** Echelon maintainers

## Summary

Add a first-class, pre-build amendment lifecycle for an existing Phase A spec.
It accepts new product evidence through repeated `--input` options, calculates
an auditable requirements/task delta, waits for explicit approval, then
re-plans the original spec in an isolated Git worktree.

The amendment must never start from the caller's current branch. It starts from
the spec branch when that branch exists, otherwise from the configured default
branch, as `echelon spec run` does. The caller's checkout, active run, tracked
changes, and untracked files remain untouched.

This is deliberately not `echelon spec run --over-spec`: `run` creates a new
spec identity, while `amend` revises an existing identity.

## Problem

Before build starts, product teams often provide new requirements or design
evidence. Current neighbouring workflows do not solve this safely:

- `echelon spec reopen` converts verified implementation gaps into follow-up
  tasks;
- `echelon spec change` handles scope changes during build.

Neither revises a planned spec while another spec is active. The manual
workaround can use the wrong branch, overwrite `runs/.current`, lose input
provenance, or read dirty source worktrees.

The Optasearch example makes the constraints concrete: planned spec 004 must
be revised while its primary checkout is on 006; its target repositories may
be dirty and lack the 004 feature branch; the new requirement and design inputs
are ignored local PDFs.

## Command surface

```bash
# Create an impact proposal and stop for approval.
echelon spec amend <spec-id> "<change summary>" \
  --input requirement:<path-or-figma-url> \
  --input reference:<path-or-figma-url>

# Inspect an in-progress or completed amendment.
echelon spec amend status <amendment-id-or-spec-id>

# Apply an approved proposal in its isolated worktree.
echelon spec amend approve <amendment-id>

# Abandon a pending proposal without changing its canonical spec.
echelon spec amend abandon <amendment-id>
```

Example:

```bash
echelon spec amend 004-transform-selector-above-stat \
  "Incorporate PBS-E-73 requirements and reference design" \
  --input requirement:sources/PBS-E-73/PBS-E-73.pdf \
  --input reference:sources/PBS-E-73/PBS-E-73-figma-design.pdf
```

`--dry-run` performs preflight only: resolve branches and inputs, check PDF
readability, and print the prospective baseline. It must not create a branch,
worktree, runtime record, or spec artifact.

## Scope

The first release:

- supports only planned, unbuilt specs; delivery-started specs use
  `echelon spec change`;
- writes spec artifacts only and never application source code;
- preserves the spec ID, target ownership, and historical product evidence;
- requires human approval between impact analysis and mutation;
- does not push, open a PR, delete branches, or clean another worktree;
- rejects target-set changes. Adding/removing targets remains a new-spec
  decision in v1.

## Decision: publish an input contract with every spec

Persist product-input intent alongside `targets.yml` in the published spec.
`inputs.yml` is the human-readable, declarative contract corresponding to the
original repeated `--input` options. The `inputs/` directory remains the
immutable, machine-verifiable evidence package that those declarations
resolved to.

```text
specs/<id>/
  targets.yml                    # current implementation-target contract
  inputs.yml                     # base product-input declaration contract
  inputs/
    manifest.json                # resource provenance, hashes, media types
    catalog.json                 # derived requirement/reference units
    snapshots/                   # immutable input bytes
```

`inputs.yml` is deliberately not a second copy of `manifest.json`. A single
input declaration may expand to many resources, so resource paths and hashes
belong only in the manifest. The YAML file preserves stable declaration
identity and original intent:

```yaml
schema_version: 1
evidence_manifest: inputs/manifest.json
evidence_manifest_sha256: "<sha256 of manifest.json>"
inputs:
  - id: PI-001
    declaration_id: requirement-001
    role: requirement
    locator: sources/PBS-E-73/PBS-E-73.pdf
  - id: PI-002
    declaration_id: reference-002
    role: reference
    locator: sources/PBS-E-73/PBS-E-73-figma-design.pdf
```

The resolver assigns `PI-*` IDs once, in declaration order for the initial
run. An amendment assigns IDs after the highest ID in the effective published
contract chain, so IDs remain unique within a spec across revisions.
`IN-REQ-*` and `IN-REF-*` remain derived catalog-unit IDs; they must never be
used as the identity of a whole input declaration. Validation requires every
`declaration_id` in `inputs.yml` to exist in the referenced manifest, with the
same role and locator, and requires the manifest digest to match. This prevents
quiet drift between the human-facing contract and immutable evidence.

### Inheritance and precedence

An amendment must reconstruct published scope, not replay a historical CLI
command and not inspect the current checkout:

1. Read the subject-spec branch's `targets.yml`; this is the authoritative
   inherited target set.
2. Read the root `inputs.yml` and its `inputs/` evidence package.
3. Read every previously promoted `amendments/<revision>/inputs.yml`, in
   numeric revision order, with its matching evidence package.
4. Add only the new `echelon spec amend --input` declarations as the current
   revision's input contract.

The ordered collection is the effective input set for the impact workflow.
Original files are never re-fetched from `locator`; agents receive their
immutable snapshots. The original run's `state.json` may be used only as a
read-only migration source, never as the normal source of truth.

`targets.yml` and the input-contract chain take precedence over any archived
run state. A disagreement is an amendment preflight conflict and must be
reported; it must not be silently reconciled from the caller filesystem.

### Amendment layout and promotion

The root contract is immutable. An amendment records only newly declared
inputs; it does not rewrite or consolidate prior contracts.

```text
specs/<id>/
  inputs.yml
  inputs/
  amendments/
    001/
      baseline.json              # ordered contracts + manifest digests
      inputs.yml                 # declarations introduced by revision 001
      inputs/
      impact.md
      decision.md
```

`baseline.json` records the ordered base/revision contract paths, their
digests, target contract digest, and target commit snapshots. A promoted
amendment is visible on the canonical spec branch and is therefore inherited
by amendment 002. A rejected or abandoned amendment remains outside the
canonical branch and is never inherited.

### Publication and migration

`echelon spec run` creates `inputs.yml` from the same
`ProductInputResolution` that creates run-local evidence. Phase-A publication
copies the evidence package and writes the contract atomically into the
published spec directory. `targets.yml` and `inputs.yml` are published together
as the spec's durable invocation contract.

For existing specs:

- if `inputs/manifest.json` exists but `inputs.yml` does not, amendment
  preflight synthesizes a proposed contract in its isolated worktree and marks
  the amendment as a provenance migration; promotion requires the normal human
  approval;
- if archived run state can corroborate the declarations, record it in the
  migration report but do not trust it over published evidence;
- if neither published evidence nor corroborating state exists, do not infer
  old `--input` values from live source files. Require explicit new `--input`
  declarations and report that historic input provenance is unavailable.

## Baseline selection

The caller checkout is not a baseline candidate.

For the control/spec repository:

1. Resolve the full canonical spec ID, for example
   `004-transform-selector-above-stat`.
2. If `refs/heads/<spec-id>` exists, use that commit.
3. Otherwise resolve the configured default branch and use its commit.
4. Require `specs/<spec-id>/spec.md` at that commit. If it is absent, fail;
   do not create a different spec.

For each target repository:

1. Use the target's declared feature branch if it can be resolved locally or
   from its configured remote.
2. Otherwise use that target repository's configured default branch.
3. Resolve and record the exact commit before model dispatch.

For Optasearch, the intended resolution is:

| Repository | Preferred ref | Fallback |
| --- | --- | --- |
| control/spec repo | `004-transform-selector-above-stat` | control default branch |
| `pressbox-search` | `004-transform-selector-above-stat` | `main` |
| `pressbox-search-api` | `004-transform-selector-above-stat` | `master` |

The recorded commit is the reproducible source baseline. If a target feature
branch is missing when delivery eventually begins, delivery creates it from
that recorded commit rather than a later default-branch head.

## Branch and worktree transaction

```text
caller worktree:            006-add-advanced-filters-pro       unchanged
canonical spec branch:      004-transform-selector-above-stat  baseline only
temporary amendment branch: amend/004-transform-selector-above-stat/001
amendment worktree:         .echelon/runtime/amend-worktrees/004.../001
```

The controller does the following:

1. Snapshot declared inputs from the caller filesystem before creating the
   worktree. This allows ignored evidence such as `sources/PBS-E-73/*.pdf`.
2. Create `amend/<spec-id>/<revision>` at the control baseline and check it out
   only in an amendment worktree.
3. Materialize each target as a detached, read-only worktree at its resolved
   commit. Never use the caller's potentially dirty target directories.
4. Run the workflow only in the amendment workspace.
5. Promote only after validation and approval with compare-and-swap:

   ```text
   git update-ref refs/heads/<spec-id> <amended-commit> <baseline-commit>
   ```

   If the canonical branch changed, promotion fails without overwriting it.
6. Retain an isolated worktree checked out on the canonical amended branch, so
   later 004 delivery work does not require switching away from 006.

`runs/.current` remains owned by ordinary Phase A. Amendment runtime state is
shared across linked worktrees under the Git common directory:

```text
<git-common-dir>/echelon/amendments/<spec-id>/<revision>/state.json
<git-common-dir>/echelon/amendments/<spec-id>/<revision>/transaction.json
<git-common-dir>/echelon/locks/amend-<spec-id>.lock
```

The lock is per spec ID, so simultaneous work on spec 006 does not block an
amendment of 004.

## Product input revisions

Existing root contracts and evidence at `specs/<id>/inputs.yml` and
`specs/<id>/inputs/` are immutable. New evidence is stored in a versioned
amendment directory; it never replaces the original contract, manifest,
catalog, snapshots, or traceability ledger.

```text
specs/<id>/
  inputs.yml                      # base input declarations, unchanged
  inputs/                         # base evidence, unchanged
  amendments/
    001/
      baseline.json
      change-request.md
      inputs.yml                  # this revision's declarations only
      inputs/
        manifest.json
        catalog.json
        snapshots/
        extracted/
        renders/
        traceability.json
      impact.md
      decision.md
      requirement-task-map.json
      validation.md
```

`baseline.json` records control and target SHAs plus hashes of the original
spec, plan, tasks, target contract, ordered input contracts, and manifests.
The amendment ledger references base evidence and maps only newly supplied
units.

### PDF normalization

Keep the existing input roles:

- `requirement:` means normative product evidence;
- `reference:` means design/context evidence.

Refactor the product-input resolver so a requirement PDF is copied unchanged,
text is extracted with page/tool provenance, and deterministic `IN-REQ-*`
units are created for page/paragraph chunks. A reference design PDF is copied
unchanged, rendered into deterministic page images, and made available as
non-normative `IN-REF-*` evidence.

If text extraction fails, use configured OCR or block before impact analysis.
The current opaque-binary fallback must never claim requirement coverage. Unit
IDs include the original PDF digest and page/chunk location; extraction and
render hashes are retained separately.

## Workflow

Register an `amend` sequence in `extension/workflow/definition.yaml` and keep
`extension/commands/echelon.amend.md` thin. The phase files define context,
outputs, and routing; agents retain their existing invariant protocols.

| Phase | Owner | Output | Canonical mutation? |
| --- | --- | --- | --- |
| `amend-0-preflight` | deterministic controller | baseline/input report | No |
| `amend-1-impact` | CHANGE CONTROLLER | `impact.md` | No |
| `amend-2-approval` | human gate | `decision.md` | No |
| `amend-3-what` | CARTOGRAPHER | revised `spec.md` | isolated branch only |
| requirements gates | controller + SAGE | current evidence | isolated branch only |
| solution impact | ARCHITECT/SENTINEL when needed | revised solution artifacts | isolated branch only |
| `amend-4-plan` | PLANNER | revised `tasks.md` + mapping | isolated branch only |
| `amend-5-promote` | deterministic controller | validation/promotion record | CAS only |

Reuse CARTOGRAPHER's existing amendment protocol, but give it explicit
amendment context and forbid it from creating a spec identity, branch, or
constitution. COMMANDER remains the only writer of run state and journal
entries.

The impact report classifies every new input unit as exactly one of:

```text
add | modify | remove | duplicate | conflict | reference-only
```

It must list affected FR/NFR/AC IDs, tasks, targets, architecture artifacts,
and unresolved product decisions. Approval is mandatory for all v1 amendments.

## Requirement and task identity

Because this command applies only before build:

- retain a requirement ID for an unchanged or narrowly clarified meaning;
- create a new ID for an independent requirement;
- record split, merge, and removal lineage in `requirement-task-map.json`;
- retain a task ID only when its deliverable and target remain materially the
  same; otherwise map the old task to a new ID;
- regenerate task dependencies, estimates, coverage, and traceability from the
  revised requirement graph;
- reject DONE or in-progress tasks at preflight and route to `spec change`.

## Implementation plan

| Area | Change |
| --- | --- |
| CLI | Add an `amend` sub-app to `src/echelon/cli_app.py`, legacy routing/help in `src/echelon/cli.py`, and a command skill registration. |
| Lifecycle | Add `src/echelon/spec_amendment.py` for baseline resolution, state, locks, worktrees, promotion, and recovery. |
| Git | Reuse atomic-write/lock patterns from `spec_lifecycle.py`, but create a per-spec lock in the Git common directory. Never call `git switch` in the caller worktree. |
| Inputs | Refactor `product_inputs.py` to emit and validate `inputs.yml`, publish it atomically with base evidence, compose immutable revision contracts, and add a PDF extraction/render adapter. |
| Controller | Add an `AmendmentController` that composes the normal squad controller with amendment state and workspace context. |
| Workflow | Add `echelon.amend`, amendment nodes in `definition.yaml`, and `workflow/phases/amend-*.md`. |
| Finalization | Publish the base input contract with evidence; append revision contracts instead of using replacement-style `_publish_product_input_evidence`. |
| Delivery | Resolve an amended spec from its canonical ref/retained worktree, avoiding stale spec copies on unrelated branches. |

## Failure handling

| Failure | Required outcome |
| --- | --- |
| Input is ignored or untracked | Snapshot it before worktree creation and record digest + original locator. |
| Published input contract and manifest disagree | Block preflight; do not guess from the original locator or current filesystem. |
| Legacy spec has evidence but no `inputs.yml` | Generate a migration candidate only in the isolated amendment worktree; require approval to publish it. |
| Legacy spec has no input evidence | Report unavailable historic provenance and require explicit new declarations. |
| PDF extraction/OCR fails | Stop before impact analysis; mutate no branch or canonical artifact. |
| Caller/target worktree is dirty | Ignore it; analyze detached clean snapshots. Never stash, reset, or delete user work. |
| Spec branch is absent | Fall back to default branch and require that it contains the named spec. |
| Target branch is absent | Use target default branch and record its exact commit. |
| Canonical branch advances | Fail CAS promotion; retain amendment branch/worktree for reconciliation. |
| Process interrupted | Recover from durable transaction state; never auto-promote or auto-clean. |
| User rejects proposal | Mark it abandoned; retain evidence/report but do not change the canonical spec. |

## Tests and acceptance criteria

Unit tests must cover baseline selection, fallback safety, per-spec locks,
compare-and-swap promotion, immutable base input preservation, stable PDF unit
IDs, unreadable-PDF blocking, input-contract/manifest agreement, and effective
contract composition across promoted revisions.

Integration tests must prove all of the following:

1. Starting an amendment from a dirty 006 worktree leaves its branch, tracked
   changes, untracked files, and `runs/.current` unchanged.
2. Dirty target repositories are not used; controllers receive clean detached
   snapshots at recorded commits.
3. A present target feature branch is preferred while a missing target feature
   branch falls back to that target's default branch.
4. Ignored local PDFs supplied with `--input` are present in immutable
   amendment evidence and available to the workflow.
5. Rejecting an amendment leaves canonical `spec.md`, `plan.md`, `tasks.md`,
   branch ref, and original inputs byte-identical to baseline.
6. A competing canonical-branch update before promotion cannot be overwritten.
7. A published `inputs.yml` and its manifest are sufficient to reconstruct the
   original input scope after the original run directory is removed.
8. A conflicting archived run state cannot override published targets or input
   evidence.

The feature is complete when a user can amend an unbuilt spec while another
spec branch is active, review the exact input/requirement/task delta, approve
the change, and obtain an amended canonical branch without altering the
caller worktree, source working directories, historic evidence, or unrelated
active run.

## Alternatives rejected

- **Use only archived run `state.json`:** run state is operational and may be
  archived, reset, or absent; it is not a published spec contract.
- **Use only `inputs/manifest.json`:** it preserves resource provenance but is
  too low-level to express stable, human-reviewable input declarations.
- **Rewrite root `inputs.yml` on every amendment:** destroys the original
  invocation contract and obscures which evidence introduced a requirement.
- **`echelon spec run --over-spec`:** confuses new-spec creation with revision
  and inherits single-active-run assumptions.
- **Switch the caller checkout:** disrupts concurrent work and violates branch
  baseline isolation.
- **Append tasks only:** appropriate for fulfillment-gap reopen, not product
  amendments that may change requirements, plans, contracts, and dependencies.
- **Use current source directories:** risks reasoning against uncommitted,
  unrelated code instead of an explicit clean commit.
