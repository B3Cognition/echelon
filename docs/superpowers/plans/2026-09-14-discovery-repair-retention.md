# Discovery repair retention implementation plan

> Use executing-plans inline and test-driven development. Independent read-only
> review is required; do not delegate implementation.

**Goal:** Preserve accepted discovery proof and original receipts while adding
an isolated, durable selection and attempt budget for a subsequent repair.

**Architecture:** Extend the existing identity release payload, Squad state
owner and secure discovery receipt files. Keep creation state and files exact.
This checkpoint establishes retention/selection contracts, not repair dispatch,
finding provenance admission, source-domain admission or public activation.

**Tech stack:** Python, existing SQLite identity storage and Squad JSON state.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`.
The user approved the compatibility extension after commit `79ca8128`:
retain full proof for all new managed discoveries, keep each repair's selection
and budget separate, and never rewrite or reconstruct existing records.

## Constraints

- Keep immutable subjects and exact existing IDs; six digits minimum for new IDs.
- Reuse existing owners, neutral Prosaic roles and Claude/Codex boundaries.
- Preserve all original operation, provider and reservation receipts.
- Initial repair plus at most two retries; no restart or reordered-finding reset.
- Missing retained proof requires reconciliation; old records are not migrated.
- No installation, live provider use, default activation, push or merge.
- Do not modify the stopped smoke workspace, AGENTS.md, CLAUDE.md or legacy build.

## Task 1: General retained completion proof

Files: `src/harness/discovery_completion.py`,
`tests/unit/test_discovery_repair_retention.py`.

- [x] Prove a normal no-checkpoint discovery retains a validated complete intent
  and receipts after outbox cleanup. Mutating those bytes must reject.
  Run `pytest tests/unit/test_discovery_repair_retention.py -q` and observe RED.
- [x] New releases use version 3 with `completion` and `proof={intent,receipts}`.
  Existing released v1/v2 records retain exact payloads on cleanup retry.
  Accept v2 full checkpoint proof on read; v1 cannot authorize repair admission.
  Validate schema/digests, retaining publication/request, protected discovery
  association, identity history and accepted source head before returning proof.
- [x] Generalize the checked spec projection to consume v2/v3 proof. Keep the
  checkpoint-specific reader strict about requiring a checkpoint effect.
- [x] Verify no-checkpoint, checkpoint, tampering and old-release cleanup cases.

## Task 2: Protected repair selection and isolated receipt files

Files: `src/harness/discovery_repair_state.py`, `src/harness/squad_state.py`,
`src/harness/discovery_receipts.py`, `tests/unit/test_discovery_repair_retention.py`.

- [x] Add failing state tests: selection preserves all original records;
  canonical finding order replays the same unit; changing scope/body for that
  origin rejects; missing selection cannot resume; begin records one attempt;
  completed replies do not reset the three-attempt ceiling; generic save cannot
  modify or delete repair state.
- [x] Implement pure repair-state validation and owning Squad transitions.
  Selection binds accepted completion ID/digests, review origin and return phase,
  exact findings, allowed artifacts and existing ID revisions. Unit identity is
  derived from accepted completion and review origin, never candidate bytes or
  findings order. One unresolved unit prevents selecting another origin.
  These are protected association data, not proof of report provenance: positive
  runtime admission must authenticate the origin and source before invoking them.
- [x] Add an optional strict 64-hex repair unit selector to the existing secure
  receipt-file owner. The default paths remain unchanged. Selected repair paths
  are distinct and cannot alias or traverse to original or other repair files.
  A missing selected file stays missing; do not auto-initialize on resume.
- [x] Test real files, independent units, traversal, symlinks and hardlinks.

## Task 3: Verify and hand off

- [x] Run new tests plus discovery normal-entry/completion/checkpoint, provider
  receipts, reservations, bootstrap, operation and Squad state regressions.
- [x] Obtain independent read-only review, address findings with red/green tests.
- [x] Record exact results and remaining runtime gaps, then commit this checkpoint.

The next runtime task must authenticate requesting review occurrences, capture
accepted graph/context/evidence with retained proof, connect the selected repair
to the existing operation/provider/publication/completion owners, and return to
the exact requesting phase. Do not claim this retention checkpoint fixes the
original renumbering failure end to end.

## Review and verification evidence

Tests first reproduced missing full proof (new no-checkpoint release version 1,
checkpoint release version 2), absent repair-owner transitions and missing receipt
namespacing. Initial no-checkpoint fixture setup incorrectly retained checkpoint
policy v2 after removing the target; restoring the actual no-checkpoint policy
made it fail on the intended missing-proof assertion before implementation.

Independent read-only review found one P2: the load validator accepted multiple
unfinished units even though selection transitions rejected them. Two real
retained-state corruption tests reproduced the gap. Validation now requires one
source completion per unit and at most one unfinished unit. The duplicate-source
case also uses an accepted first unit so the unfinished limit cannot mask it.
The reviewer independently confirmed the rejection cases and that an accepted
previous unit plus a new selected unit remains valid. No remaining findings.

Final fresh verification:

- `test_discovery_repair_retention.py`: **18 passed in 59.05s**, including exact
  original-receipt preservation and independent duplicate-source validation.
- Discovery bootstrap/operation/turns/reservations/completion/normal-entry/
  checkpoint, Squad completion/state and lock-order suites:
  **840 passed in 430.80s**.
- Complete Squad controller integration suite: **514 passed in 325.30s**.
- Total: **1,372 passed**. `git diff --check` is clean.

The approved retention/selection extension is complete and independently reviewed.
Keep the branch/worktree for continued convergence. Runtime provenance admission,
provider dispatch for the selected repair, accepted graph/context/evidence capture,
subsequent publication/checkpoint integration and the original end-to-end repair
acceptance remain open. No installation, migration, live spending or activation.
