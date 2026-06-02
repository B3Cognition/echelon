# Spec Fulfillment Verification Design

## Goal

Add a read-only Echelon workflow that answers: "Does the current implementation fully satisfy this spec?" without requiring a full brownfield reverse-engineering run.

## Problem

`echelon harness run` and `echelon land` can prove that configured verification commands pass, but they do not prove that every requirement, user story, acceptance criterion, and edge case in `specs/<spec-id>-*/spec.md` was implemented. If harness state is wrong or a spec is incorrectly marked complete, the current recovery option is effectively a broad brownfield run, which is too heavy for a targeted completeness check.

## Proposed Commands

### `speckit.echelon.verify-spec`

Read-only command.

Input:
- `spec_id` such as `001`
- Optional `strict=true|false`

Reads:
- `specs/<spec-id>-*/spec.md`
- `tasks.md`
- `coverage-map.md` if present
- `verification-summary.md`, `gap-report.md`, `fulfillment-report.md` if present
- current source tree and tests
- harness state/PR metadata if present
- fresh structural evidence:
  - run the CodeGraph bridge for the current source tree before mapping implementation evidence
  - write verification-local artifacts under `runs/<run-id>/verify-spec/<spec-id>/` when an active run exists
  - when no active run exists, create `runs/verify-spec-<spec-id>-<timestamp>/`
  - read `codegraph-summary.json` first and `codegraph-analysis.json` only when symbol-level trace is needed

Writes:
- `specs/<spec-id>-*/fulfillment-report.md`
- `specs/<spec-id>-*/fulfillment-gaps.md` only when gaps exist

Never writes application source files. Never changes spec status.

### `speckit.echelon.reopen`

Mutating command for confirmed gaps.

Input:
- `spec_id`
- Optional source report path, defaulting to latest `fulfillment-gaps.md`

Actions:
- Set spec frontmatter/status to `In Progress`.
- Append gap-derived tasks to `tasks.md` as `FG-T*` tasks.
- Add a short reopen note to `fulfillment-report.md` or `reopen-{n}.md`.
- Preserve existing harness/build history.

After reopening, the normal flow is:

```text
echelon verify-spec 001
echelon reopen 001
echelon harness run 001
echelon land 001
```

## Requirement Status Model

Each extracted requirement receives exactly one status:

- `IMPLEMENTED` — credible source and/or test evidence shows the requirement is implemented.
- `PARTIAL` — some behavior exists, but an edge case, acceptance criterion, or path is missing.
- `UNVERIFIED` — implementation may exist, but no executable or inspectable evidence proves it.
- `MISSING` — no credible implementation evidence found.
- `DEVIATED` — implementation contradicts the spec.
- `OBSOLETE_SPEC` — implementation intentionally differs and the spec likely needs updating.

Only `IMPLEMENTED` is green. `OBSOLETE_SPEC` is not a build task by default; it is a spec review task.

## Agent Workflow

### SPEC-FULFILLMENT-AUDITOR

Extracts a canonical checklist from `spec.md`:
- functional requirements
- acceptance criteria
- user stories
- entities and state transitions
- edge cases
- non-functional requirements with measurable signals

Output: `fulfillment-checklist.json` or an internal checklist section in `fulfillment-report.md`.

### IMPLEMENTATION-MAPPER

Maps checklist items to evidence:
- source files
- tests
- routes/endpoints/UI flows
- configuration
- generated artifacts
- CodeGraph symbol and call relationships when available

Always refreshes CodeGraph before mapping unless `--no-codegraph` is explicitly passed. Reads the refreshed summary first. Reads the refreshed full graph only for symbol-level trace or impact evidence.

If CodeGraph cannot run, verification may continue in degraded mode, but the report must include:
- `structural_evidence: degraded`
- the exact failure or skip reason
- lower confidence for source-only mappings that lack graph evidence

### SPEC-GUARD

Judges each requirement using the status model and produces:
- evidence table
- missing/deviated/partial/unverified findings
- confidence level
- recommended next action

### SENTINEL

For each actionable gap, proposes tests or smoke checks. These become `FG-T*` tasks when `reopen` is run.

## Artifact Format

`fulfillment-report.md`:

```markdown
# Fulfillment Report: <spec-id>

## Summary

Structural evidence: fresh CodeGraph summary generated at `<path>`  
Structural status: ready

| Status | Count |
|---|---:|
| IMPLEMENTED | 0 |
| PARTIAL | 0 |
| UNVERIFIED | 0 |
| MISSING | 0 |
| DEVIATED | 0 |
| OBSOLETE_SPEC | 0 |

## Requirement Matrix

| ID | Status | Evidence | Confidence | Notes |
|---|---|---|---|---|
| FR-001 | IMPLEMENTED | `src/notifications/service.ts`, `tests/notifications.test.ts` | high | Sends notification after persisted event. |

## Recommended Action

<NO_ACTION | REOPEN_FOR_GAPS | SPEC_REVIEW | BUGFIX_ONLY>
```

`fulfillment-gaps.md`:

```markdown
# Fulfillment Gaps: <spec-id>

## Implementation Gaps

- **FG-001**
  - Requirement: FR-001
  - Status: MISSING
  - Expected behavior: User receives an in-app notification after a successful purchase.
  - Evidence searched: `src/purchases/`, `src/notifications/`, `tests/`, CodeGraph callers for `completePurchase`.
  - Proposed test: Add an integration test that completes a purchase and asserts a notification record is created.
  - Proposed task: Implement notification creation in the purchase completion path.

## Spec Review Items

- **SR-001**
  - Requirement: FR-004
  - Status: OBSOLETE_SPEC
  - Reason: Spec requires email notification, but accepted architecture decision ADR-004 changed delivery to in-app only.
```

## Harness Integration

`echelon harness run` should read, in this order:
1. latest `bugfix-*.md`
2. `fulfillment-gaps.md`
3. `lessons.md`

Fulfillment gaps are not bugfixes. They are missing-spec-coverage tasks and should be passed to the build step as mandatory implementation context.

## Freshness and Trust

`verify-spec` must not trust stale brownfield artifacts. It should generate verification-local CodeGraph artifacts on every run:

```text
runs/<run-id>/verify-spec/<spec-id>/codegraph-analysis.json
runs/<run-id>/verify-spec/<spec-id>/codegraph-summary.json
```

When no active run exists, `verify-spec` creates a dedicated verification run:

```text
runs/verify-spec-<spec-id>-<timestamp>/state.json
runs/verify-spec-<spec-id>-<timestamp>/codegraph-analysis.json
runs/verify-spec-<spec-id>-<timestamp>/codegraph-summary.json
```

Verification runtime artifacts never use `.specify/`; `.specify/` remains for extension/config internals.

The report records:
- source tree commit/hash when available
- generated_at timestamp
- CodeGraph index state
- whether full graph was read or only summary was used
- whether verification ran in degraded mode

This keeps `verify-spec` targeted while avoiding stale structural evidence from an older RE run.

## Land Integration

`echelon land` should warn, and optionally block in strict mode, when the latest `fulfillment-report.md` has unresolved:
- `MISSING`
- `PARTIAL`
- `DEVIATED`

`UNVERIFIED` should warn unless `strict=true`.

## Why Not Full Brownfield RE?

Brownfield RE answers "what does this codebase do?" This workflow answers "does this implementation satisfy this specific spec?" It is narrower, cheaper, and produces actionable gap tasks instead of broad migration/domain artifacts.

## Implementation Order

1. Add report parser/writer helpers and tests.
2. Add a verification-local CodeGraph refresh helper and tests.
3. Add `verify-spec` command and workflow phases.
4. Add fulfillment agents/prompts.
5. Add `reopen` command that converts gaps to `FG-T*` tasks.
6. Teach harness to read `fulfillment-gaps.md`.
7. Teach land to warn/block based on unresolved fulfillment report statuses.
