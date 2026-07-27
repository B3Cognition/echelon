# Final Review Fix Report

Status: DONE

## Scope

Implemented the final Critical/Important MemPalace audit fixes as one coherent
wave. Public commands remain under `echelon`; parsing and deterministic drawer
identity remain owned by the existing `codegen.memory.requirements_miner`
implementation.

## Findings Addressed

1. Canonical Echelon configuration

- `RequirementMemoryAdapter` now reads `.echelon/config.yml` first and falls
  back to the legacy extension config only when the canonical file is absent.
- It constructs `MemPalaceContext` with `from_wing()`, so canonical-only
  workspaces no longer require a legacy config.
- Tests cover canonical precedence plus canonical-only mine, audit, and CLI
  audit paths without `SystemExit`.

2. Strictly read-only audit

- Added a lower-level read-only collection open that calls MemPalace
  `get_collection(..., create=False)`.
- Audit consumes only the adapter's public read-only open and no longer reaches
  the writer's creating `_get_collection()` path.
- Missing collections remain bounded `unavailable` reports and are never
  created by audit.

3. Structured expected rows and room correctness

- Added `plan_canonical_requirement_drawers()` beside the existing canonical
  ID planner. It reuses the shared parser, secret scrubbing, and deterministic
  identity function and returns requirement ID, room, artifact hash, canonical
  spec hash, and requirement content hash.
- The existing ID-only planner now projects IDs from those shared rows.
- Echelon converts shared rows into Echelon-owned
  `PlannedRequirementDrawer` values for audit.
- Audit compares actual room to each expected row's room. Exact `SEC-*`
  drawers pass in `security-requirements`; mismatches report `wrong_room`.

4. Stale extras and duplicates

- Audit performs a read-only wing-filtered scan capped at 1,000 rows.
- Rows referencing the audited canonical spec are checked for stale hashes,
  removed requirements, run-local/non-canonical provenance, excluded
  lifecycle states, and duplicate current requirement drawers.
- Audit reports findings only; it does not delete or rewrite storage.

5. Error classification

- Planner `ValueError` becomes a bounded `fail` audit report or `partial` mine
  report instead of escaping or being labeled backend unavailable.
- Structurally unusable collection responses remain `unavailable`.
- Rows with usable IDs but malformed document or metadata fields become
  drawer-specific `invalid_document`, `invalid_metadata`, or
  `duplicate_response_id` findings.
- Storage-operation exceptions remain bounded backend-unavailable reports.

6. Mine outcomes

- `MineResult` now preserves `written`, `already_present`, `drifted`, `failed`,
  and `unavailable` independently.
- Adopted and unavailable drawers are no longer double-counted as skipped.
- Echelon reads explicit drift and unavailable counts instead of inferring
  drift from unresolved IDs.
- Deterministic drift and non-backend write failures produce `partial`; actual
  backend outages produce `unavailable`.
- Exact writes classify validation/data failures as `failed` while retaining
  backend failures as `unavailable`.

## Minor Coverage

- `mine --write-report` suppresses unavailable reports.
- Added CLI coverage for `audit --write`, unavailable audit write suppression,
  and `refresh --no-audit`.

## Verification

- `python -m pytest tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_audit.py tests/unit/test_requirements_miner_ctx.py tests/unit/test_mempalace_writer.py tests/unit/test_mempalace_context.py tests/unit/test_mempalace_collision.py tests/unit/test_mempalace_reader.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_typer_app.py tests/unit/test_squad_completion.py tests/integration/test_mempalace_mine_search.py tests/integration/test_squad_context_memory.py -q`
  -> 357 passed.
- `python -m compileall -q` on all touched production modules -> exit 0.
- `git diff --check` -> exit 0.
- Typer `spec memory --help` -> exit 0 and lists `mine`, `audit`, and `refresh`.

## Concerns

None.

## Final Fix Follow-up

Status: DONE

- Canonical planning now bounds all local planner exceptions as deterministic
  audit `fail` reports rather than handling only `ValueError`.
- `reconcile_drawers()` now runs inside a local deterministic-failure
  boundary. Reconciliation faults preserve the spec identity and expected
  count, report only the exception class, and add the
  `reconciliation_failed` recommendation.
- Exact drawer validation now requires both `scope: canonical` and
  `canonical: true`. An otherwise exact drawer with run-local scope is
  classified as non-canonical and fails the audit.
- Added regressions for non-`ValueError` planner faults, reconciliation
  exceptions, and run-local scope false-passes.

Verification:

- `python -m pytest tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_audit.py tests/unit/test_requirements_miner_ctx.py tests/unit/test_mempalace_writer.py tests/unit/test_mempalace_context.py tests/unit/test_mempalace_collision.py tests/unit/test_mempalace_reader.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_typer_app.py tests/unit/test_squad_completion.py tests/integration/test_mempalace_mine_search.py tests/integration/test_squad_context_memory.py -q`
  -> 360 passed.
- `python -m compileall -q src/echelon/mempalace_audit.py` -> exit 0.
- `git diff --check` -> exit 0.

Concerns: None.
