# Graph Lifecycle Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a landed specification’s graph represent its current canonical requirement and verification state without treating retained history as a current failure, while preserving evidence provenance and resolving valid target paths without a published RE source.

**Architecture:** Keep the current graph schema and audit entrypoints. Tighten MemPalace audit classification so only positively scoped active corruption blocks a member. Add a versioned, receipt-backed fulfillment-reconciliation service that can repair stale ledger conclusions only from compatible immutable evidence. Teach workspace composition to create a path-validated source snapshot when `targets.yml` identifies an in-root source that is not otherwise represented by a published RE graph.

**Tech Stack:** Python 3.11+, Typer CLI, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-graph-lifecycle-evidence-design.md`

## Global Constraints

- Preserve existing `echelon spec verify`, delivery verification, graph refresh, and ledger-reuse behavior; reconciliation is an additional explicit capability, not a replacement for authoritative verification.
- Treat a candidate commit SHA as provenance only. Product-content, requirement-set, and contract fingerprints determine compatibility.
- Never infer legacy evidence from fulfillment-report prose. Legacy reconciliation must reconstruct exact evidence from immutable inventories and require an immutable spec snapshot.
- Never mutate a ledger as a side effect of `echelon graph workspace refresh`; only `echelon spec reconcile-fulfillment --write` and final landing may write a reconciled ledger.
- A declared `targets.yml` path may resolve inside the canonical workspace root even when `.echelon/config.yml` has no `sources` registry (as in the demo workspace); configured source entries still take precedence for source identity. Paths must exist as directories and be deterministic. Ambiguous or out-of-root paths remain warnings with no guessed graph edge.

---

## Task 1: Classify MemPalace history separately from active corruption

**Files:**
- Modify: `src/echelon/mempalace_memory_audit.py`
- Modify: `src/echelon/mempalace_audit.py`
- Modify: `tests/unit/test_mempalace_audit.py`
- Modify: `tests/unit/test_mempalace_spec_evidence.py`
- Modify: `tests/unit/test_mempalace_requirements.py`

- [ ] **Step 1: Add failing audit tests.** Build fixtures with a complete current expected drawer set plus: (a) a same-spec noncanonical/superseded historical drawer, (b) an active canonical duplicate for an expected requirement, (c) a same-spec canonical drawer with an invalid room/wing, and (d) malformed foreign/unscoped data. Assert respectively: pass/warn with `historical`, fail with `duplicate_canonical`, fail with `scope_collision`/`malformed_extra`, and workspace-integrity warning without member failure.

- [ ] **Step 2: Run the focused tests and confirm they fail against the current blanket-extra policy.**

  Run: `pytest -q tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_mempalace_requirements.py`

- [ ] **Step 3: Extend both audit report families and rendering.** Add stable collections for `historical`, `duplicate_canonical`, `scope_collision`, `malformed_extra`, and `global_memory_integrity` to `ArtifactMemoryAuditReport` and `SpecMemoryAuditReport`; preserve existing serialized fields for compatibility. Extract/share classification predicates rather than letting the generic evidence audit and requirement-memory audit drift. Render historical and global-integrity counts explicitly so a CLI user can distinguish retained history from a blocking failure.

- [ ] **Step 4: Replace both extra-drawer scans with one scope-aware classification policy.** Query the wing as today, but only make a member-blocking classification after metadata positively identifies the current `spec_id` and current artifact kind. Apply the policy to generic evidence rows and requirement-memory rows: terminal/superseded/noncanonical history is `historical`; an active canonical identity for an expected requirement is `duplicate_canonical`; active same-spec metadata whose canonical identity/wing/room conflicts is `scope_collision` or `malformed_extra`. Put foreign or unscoped malformed rows in `global_memory_integrity` and do not use them to fail this member.

- [ ] **Step 5: Make status calculation use only blocking collections.** Missing/current-row integrity failures and the three active-extra failure classes fail. Historical history and global integrity conditions warn; preserve `duplicate` as compatibility output while populating the specific duplicate class.

- [ ] **Step 6: Run focused tests and commit.**

  Run: `pytest -q tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_mempalace_requirements.py`

  Commit: `fix: distinguish historical mempalace drawers from active corruption`

## Task 2: Create the receipt-backed fulfillment reconciliation model

**Files:**
- Modify: `src/harness/verified_fulfillment_ledger.py`
- Create: `src/harness/fulfillment_reconciliation.py`
- Modify: `tests/unit/test_verified_fulfillment_ledger.py`
- Create: `tests/unit/test_fulfillment_reconciliation.py`

- [ ] **Step 1: Add failing model tests.** Cover ledger v1 read compatibility and v2 write/read round-trip; a later compatible passed receipt replacing an `UNVERIFIED` row; aggregation of two compatible successes; changed candidate content; changed requirements; missing immutable spec snapshot; changed/missing/executable inventory entry; and a contradictory complete status. Assert unsafe evidence returns an explicit `reverify_required` outcome and never silently resolves a requirement.

- [ ] **Step 2: Run the focused tests to establish the missing reconciliation seam.**

  Run: `pytest -q tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_fulfillment_reconciliation.py`

- [ ] **Step 3: Version the ledger schema without breaking readers.** Keep `VerifiedLedgerRow`’s existing fields, then add v2 fields: immutable `receipt_refs` (path + receipt/evidence digest), `candidate_content_fingerprint`, `contract_hash`, `requirement_set_fingerprint`, and `selected_evidence`. `read_verified_ledger` must accept v1 files with empty v2 fields; `write_verified_ledger` emits schema version 2 and deterministically orders rows/references.

- [ ] **Step 4: Implement pure reconciliation in `fulfillment_reconciliation.py`.** Define input records for a parsed receipt, immutable product inventory, immutable spec snapshot, and current target/spec fingerprints. Validate only harness-owned successful receipts using `validate_equivalent_product_receipt`; compare normalized product content to the current landed target, verify spec-input/requirement fingerprints, and compare legacy inventory entries by exact path/kind/executable/content hash. Treat Markdown reports as display metadata only. Return a deterministic result containing updated rows, selected evidence, retained compatible receipts, and machine-readable reasons.

- [ ] **Step 5: Define compatibility and conflict selection precisely.** A verified candidate may replace an unresolved row only when it has a complete requirement row and all three fingerprint domains match. Aggregate compatible successes and choose primary evidence by `(verified_at, receipt_sha256)`, retaining all references. Mark conflict only for incompatible, incomplete, or contradictory complete evidence for the same compatible content; do not mark multiple compatible successes as conflict.

- [ ] **Step 6: Preserve existing reuse semantics.** Keep `plan_verified_ledger_reuse`’s public behavior for v1/v2 rows. Use selected evidence/artifact hashes when present, and retain current artifact invalidation as the cache guard.

- [ ] **Step 7: Run tests and commit.**

  Run: `pytest -q tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_fulfillment_reconciliation.py`

  Commit: `feat: add receipt-backed fulfillment reconciliation`

## Task 3: Connect new verification and landing to the canonical ledger

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Modify: `src/harness/land.py`
- Modify: `src/harness/coordinator.py`
- Modify: `tests/unit/test_land.py`
- Modify: `tests/unit/test_fulfillment_runner.py`

- [ ] **Step 1: Add failing integration tests.** Create a current target with a verified product fingerprint and a successful harness receipt. Assert final landing writes a v2 ledger whose completed rows refer to the receipt and current fingerprints. Create a merge-only commit/content-equivalent candidate and assert it remains valid. Assert a content-mutated candidate or absent receipt cannot land/reconcile as verified.

- [ ] **Step 2: Run the focused tests.**

  Run: `pytest -q tests/unit/test_land.py tests/unit/test_fulfillment_runner.py`

- [ ] **Step 3: Populate v2 fields for new authoritative verification.** In `FulfillmentRunner._write_verified_fulfillment_ledger`, obtain the authoritative `VerificationEvidenceRef`, verified product fingerprint, contract/coverage hash, and canonical requirement-set/spec-input hash from the same run state rather than rebuilding evidence from Markdown. Attach them to every completed requirement row while preserving report-derived evidence paths as explanatory references.

- [ ] **Step 4: Reconcile at final landing.** In the final successful landing path in `land.py`, construct the current target/spec evidence context and invoke the pure reconciler before the final ledger write. Persist a landing receipt/result only if reconciliation reports compatible evidence; otherwise preserve the unresolved row and expose `reverify_required` to the existing fulfillment guard. Do not require exact commit equality when the product fingerprint is unchanged.

- [ ] **Step 5: Ensure coordinator state exposes immutable inputs.** Persist the receipt reference, current `verified_product_fingerprint`, verification contract digest, requirement-set/spec-input digest, and immutable inventory/snapshot paths needed by later reconciliation. Do not copy mutable worktree paths into immutable claims.

- [ ] **Step 6: Run focused tests and commit.**

  Run: `pytest -q tests/unit/test_land.py tests/unit/test_fulfillment_runner.py tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_fulfillment_reconciliation.py`

  Commit: `fix: reconcile verified fulfillment during landing`

## Task 4: Expose an explicit, non-mutating-by-default reconciliation command

**Files:**
- Modify: `src/echelon/cli_app.py`
- Create: `tests/unit/test_cli_spec_reconcile_fulfillment.py`
- Modify: `tests/unit/test_cli_spec_verify.py` (or the existing CLI spec test module that owns `spec` commands)

- [ ] **Step 1: Add failing CLI tests.** Invoke `echelon spec reconcile-fulfillment <spec>` against fixtures representing a compatible legacy receipt, a missing immutable snapshot, and no candidates. Assert default output is a deterministic preview, exit status differentiates success/reverify-required/no-candidate, and no ledger changes occur. Assert `--write` atomically updates only a reconciliation-eligible ledger and emits its reconciliation receipt path.

- [ ] **Step 2: Run the focused CLI tests.**

  Run: `pytest -q tests/unit/test_cli_spec_reconcile_fulfillment.py`

- [ ] **Step 3: Add `spec reconcile-fulfillment`.** Resolve the canonical spec through the existing `find_spec_dir` conventions; discover only immutable delivery receipts/inventories/snapshots under the orchestration root; call the pure reconciler; render rows, selected receipt IDs, and explicit reasons. Add `--write` as the sole mutation flag and `--json` for automation.

- [ ] **Step 4: Enforce mutation boundaries.** The command must refuse to write an incomplete/conflicting/reverify-required proposal. `echelon graph workspace refresh` and `echelon spec verify` remain non-reconciliation callers unless they are executing a fresh authoritative verification.

- [ ] **Step 5: Run tests and commit.**

  Run: `pytest -q tests/unit/test_cli_spec_reconcile_fulfillment.py tests/unit/test_land.py`

  Commit: `feat: add explicit fulfillment reconciliation command`

## Task 5: Materialize path-validated source snapshots in workspace graphs

**Files:**
- Modify: `src/echelon/workspace_graph.py`
- Modify: `tests/unit/test_workspace_graph.py`
- Modify: `tests/unit/test_workspace_graph_audit.py`

- [ ] **Step 1: Add failing graph tests.** Configure a workspace source root and a spec `targets.yml` path that exists beneath it but has no published RE source graph. Assert the workspace graph has one deterministic `SourceSnapshot` node, a `SPEC TARGETS` edge, and a fresh source fingerprint. Add tests for duplicate configured source match, absent target directory, a path outside configured roots, and two conflicting target identities; assert warnings/no guessed target edge for each invalid case.

- [ ] **Step 2: Run graph tests.**

  Run: `pytest -q tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py`

- [ ] **Step 3: Introduce source-root/path resolution helpers.** Extend `_Source`/workspace config handling with resolved paths and a deterministic candidate resolver. Match in this order: a declared `targets.yml` path inside the canonical workspace root (using a configured source entry when it exactly matches); an explicit current workspace target-registry mapping; then one published landing-receipt source path inside the canonical workspace root. A workspace with no configured source registry may therefore create a path-backed snapshot, but receives no invented symbolic source ID.

- [ ] **Step 4: Add `SourceSnapshot` nodes only for valid unresolved paths.** Hash an explicit deterministic file inventory for the resolved source path, store source id/path/fingerprint/provenance in node properties, and attach the `TARGETS` edge. Reuse existing `SourceRoot` identity if a published RE source exists; never replace a source root with a snapshot.

- [ ] **Step 5: Preserve safety and audit behavior.** Emit machine-readable warnings for ambiguous/outside/missing target paths. Ensure graph validation accepts `SourceSnapshot` with the same edge semantics and does not treat it as an RE claim.

- [ ] **Step 6: Run tests and commit.**

  Run: `pytest -q tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py`

  Commit: `fix: compose workspace targets without published re sources`

## Task 6: Update graph/audit reporting and prove the demo regression closes

**Files:**
- Modify: `src/echelon/spec_graph.py`
- Modify: `src/echelon/spec_graph_audit.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_spec_graph_audit.py`
- Modify: `tests/unit/test_workspace_graph.py`

- [ ] **Step 1: Add failing audit/rendering tests.** Assert a row reconciled from complete compatible receipt evidence produces a complete `VERIFIED_BY` edge and audit pass. Assert no receipt or `reverify_required` still produces the existing missing-verified-evidence failure. Assert CLI/report output calls out historical MemPalace records as warnings rather than incorrectly reporting a failed current spec.

- [ ] **Step 2: Run focused tests.**

  Run: `pytest -q tests/unit/test_spec_graph_audit.py tests/unit/test_workspace_graph.py`

- [ ] **Step 3: Make graph evidence fields transparent.** Include v2 selected evidence, product fingerprint, and reconciliation outcome on the existing `VERIFIED_BY` edge. Keep `complete` derived solely from a complete reconciled row, not from presence of a report or commit SHA.

- [ ] **Step 4: Update audit messaging only where classifications changed.** Preserve genuine audit failures; add remediation text distinguishing `reverify_required` from historical drawer retention and target-resolution warnings.

- [ ] **Step 5: Validate the real demo workspace without mutating it until the explicit step.** From `/Users/michalbachorik/work/browser-3d-game-stack-smoke`, run: `echelon spec reconcile-fulfillment 003-create-browser-first-3d` and inspect the preview. If it reports compatible immutable evidence, repeat with `--write`; if it correctly reports `reverify_required`, run its prescribed fresh verification instead. Then run `echelon graph workspace refresh --write` and `echelon graph workspace audit`. Confirm historical 003/006 drawers no longer exclude the member and the path-backed browser target is represented; do not delete pre-existing untracked graph artifacts or the Banzai lock.

- [ ] **Step 6: Run full relevant suite and commit.**

  Run: `pytest -q tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_mempalace_requirements.py tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_fulfillment_reconciliation.py tests/unit/test_land.py tests/unit/test_fulfillment_runner.py tests/unit/test_cli_spec_reconcile_fulfillment.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_spec_graph_audit.py`

  Commit: `fix: report current graph lifecycle evidence accurately`

## Final verification

- [ ] Run the complete unit suite prescribed by the repository’s standard test command.
- [ ] Run `git diff --check` and `git status --short`; retain only intentional changes.
- [ ] Review the generated workspace graph/audit in the demo workspace, preserving any user-owned untracked files.
- [ ] Confirm no graph refresh path rewrites a fulfillment ledger and that the CLI preview never mutates it.
