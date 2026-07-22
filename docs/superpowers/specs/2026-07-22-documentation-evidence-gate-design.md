# Documentation Evidence Gate Design

## Problem

The delivery documentation gate currently accepts a caller-provided list of
changed paths. Ralph builds that list from uncommitted worktree changes. When
an agent commits `README.md` and `CHANGELOG.md` before verification, the
worktree is clean and the gate incorrectly reports that neither document
changed. The current path check is also too weak as a quality signal: a
cosmetic edit can prove provenance without documenting delivered behavior.

## Goals

- Recognize documentation changes committed anywhere in the active delivery
  slice, including post-task and docs-only commits.
- Keep deterministic provenance separate from semantic documentation quality.
- Require every documentation-relevant delivered change to be documented or
  explicitly and defensibly classified as not applicable.
- Verify documentation claims against implementation and runtime evidence.
- Return actionable failures naming uncovered changes and weak or unsupported
  claims.
- Preserve existing containment boundaries and external spec-artifact support.

## Non-goals

- Replacing the TECH WRITER or DOCS VERIFIER agents.
- Treating every source file as user-visible documentation scope.
- Requiring README or CHANGELOG edits for genuinely internal-only deliveries.
- Reworking fulfillment evidence or task checkpoint semantics.

## Architecture

The gate has two independent layers. Both must pass when documentation is
required.

### Layer 1: deterministic provenance

Ralph derives the documentation delivery slice from a stable delivery baseline
and the current `HEAD`, then unions committed paths with staged, unstaged, and
untracked paths. The baseline is the delivery branch point or another existing
harness-owned baseline already used to define the delivery. It is not the most
recent task checkpoint because documentation can legitimately be committed
after all tasks are complete.

The provenance record contains:

- baseline commit;
- current `HEAD`;
- normalized changed paths;
- whether `README.md` changed;
- whether `CHANGELOG.md` changed.

The existing requirement that both files change remains when `docs_required`
is true, but it becomes a trustworthy reachability check rather than a check of
only the dirty worktree.

### Layer 2: semantic coverage and correctness

`documentation-impact-report.md` gains a versioned `documented_changes` list.
Each entry maps one delivered, documentation-relevant change to implementation
evidence and documentation locations:

```yaml
schema_version: 2
docs_required: true
documented_changes:
  - change_id: FR-003
    evidence_paths:
      - src/resolve/lookup.ts
      - tests/unit/resolve/lookup.test.ts
    audience_impact: library users
    readme_sections:
      - Runtime resolution
    changelog_sections:
      - Added / Runtime resolution API
    disposition: covered
```

A change may use `disposition: not_applicable` only with a non-empty reason.
The impact report must not invent paths outside the delivery repository.

DOCS VERIFIER independently checks the coverage map against the delivery diff,
spec requirements, public exports, CLI surfaces, configuration schemas, tests,
and measured artifacts. Its report identifies:

- the reviewed change IDs;
- uncovered documentation-relevant changes;
- unsupported or contradicted claims;
- usability gaps;
- blocking findings and final verdict.

The deterministic gate validates report schemas, requires matching change-ID
coverage, checks cited paths exist, requires a passing independent verdict, and
requires zero blocking findings. Semantic conclusions remain agent-produced,
but Python prevents incomplete, malformed, or internally inconsistent evidence
from being accepted.

## Change Inventory

The harness assembles the candidate inventory from existing authoritative
inputs rather than asking an LLM to invent it:

- scoped completed requirement/task identifiers;
- committed and uncommitted delivery paths;
- detected public API, CLI, configuration, operational, setup, and significant
  performance changes;
- fulfillment evidence already produced for the delivery.

TECH WRITER assigns a coverage disposition to every candidate. DOCS VERIFIER
may add a candidate found through direct inspection, but may not silently drop
one supplied by the harness. Internal tests and refactors can be marked not
applicable with justification.

## Data Flow

1. Ralph resolves the delivery baseline and computes cumulative changed paths.
2. Ralph builds the documentation change inventory and supplies it to the
   documentation phases.
3. TECH WRITER updates README and CHANGELOG as needed and writes the versioned
   impact report.
4. DOCS VERIFIER independently checks accuracy, coverage, and usability and
   writes its versioned verification report.
5. Ralph recomputes provenance at verification time, so agent-created commits
   are included.
6. Python validates provenance, coverage-map integrity, cited evidence, and the
   independent verdict.
7. Failures identify missing files, uncovered change IDs, invalid citations, or
   unsupported claims separately.

## Failure Handling

- Missing committed documentation: `documentation-required-without-doc-changes`.
- Missing inventory disposition: `documentation-coverage-incomplete`, listing
  change IDs.
- Invalid or missing evidence path: `documentation-evidence-invalid`.
- Unsupported or contradicted claim: `documentation-claim-unsupported`.
- Failed independent review: `docs-verification-report-failed` with blocking
  finding summaries.
- A no-impact delivery remains eligible for a Ralph-owned not-applicable report
  only when both cumulative provenance and the candidate inventory contain no
  documentation-relevant changes.

## Compatibility

Existing schema-version-1 reports remain readable during active recovery runs,
but they cannot satisfy the stronger semantic coverage gate for a new delivery
that declares documentation required. New documentation phases emit version 2.
This avoids making a blocked historical state unreadable while preventing new
deliveries from using the weaker evidence contract.

## Testing

Tests reproduce the original failure and cover both layers:

- docs committed after all task checkpoints pass provenance validation;
- a clean worktree with no docs commit fails;
- staged, unstaged, and untracked changes are included;
- cosmetic docs changes without inventory coverage fail;
- missing change IDs fail with actionable identifiers;
- nonexistent evidence paths fail;
- unsupported claims or a failing verifier verdict fail;
- a complete, evidence-backed coverage map passes;
- internal-only deliveries with justified not-applicable dispositions pass;
- cumulative evidence does not include unrelated changes outside the delivery
  baseline.

## Recovery Contract

Blocked runs retain the baseline, last observed `HEAD`, documentation evidence
metadata, and worktree salvage reference before cleanup. Resume recreates a
worktree from the last reachable delivery head, recomputes cumulative evidence,
and retries verification. If the head is no longer reachable, recovery creates
a new docs-only commit from the saved patch or reruns the bounded documentation
phase, then records that commit in the resumed delivery slice.
