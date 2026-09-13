# Convergence dependency boundary

## Baseline and authorization

Read-only dependency review on 2026-09-13, implementation HEAD `4223b46b`,
upstream baseline `2c655b3d`. The branch changes 96 Python source files relative
to that upstream. Existing uncommitted deferred-scope documentation is retained.

The user authorized the convergence phases and subsequently approved necessary
dependencies from deferred work. This is not authority to introduce unrelated
capabilities, silently replace the agreed design, install, migrate, or run live
providers. This record implements convergence phase 1's keep/defer checkpoint;
the later authorization permits continuation without another dependency approval.

## Result: narrow activation, not an unproven file deletion

Retain the existing implementation on the isolated branch and finish the required
controller paths. Defer broader capabilities and their rollout. Do not remove
the coupled identity infrastructure to make the diff look smaller: that would
require additional refactoring and fresh compatibility work. This decision
reduces remaining feature scope, not the existing release diff or review burden.
No extraction, rollback or dependency rewrite was performed by this review.

The original delivery changes form a separate behavioral/test boundary. They
can be reviewed independently; an independently mergeable patch has not been
constructed or verified. Identity integration remains a separate acceptance
milestone, even if both eventually ship from the same branch.

## Keep and defer map

Paths in this table are repository-relative. Keep each retained implementation's
existing tests; deferring activation does not justify deleting regression coverage.

| Surface | Disposition and reason |
| --- | --- |
| `src/harness/delivery_prompt.py`, `delivery_slice.py`, `delivery_slice_runner.py`, `delivery_slice_journal.py` | Keep original delivery orchestration and durable review receipts. No direct imports of identity modules in these delivery-specific modules. |
| Delivery changes in `src/harness/coordinator.py`, `ralph.py`, `visual_ralph.py`, `config.py`, `prompt_framing.py`, `prosaic_prompt_loader.py`, `product_inventory.py`; delivery roles and runtime wiring | Keep with the delivery slice. Shared-file hunks must be reviewed independently of identity additions; do not cherry-pick entire current shared files as a supposedly delivery-only patch. |
| `src/kernel/element_ids.py`, task/requirement readers and producers, numeric compatibility in internalization scripts and prose | Keep requested six-digit-minimum/unbounded compatibility and exact legacy labels. Formatting and consumer compatibility are not durable producer allocation. |
| `src/harness/element_identity_store.py`, schema, lifecycle, binding, candidate, source and publication modules | Retain the coupled authority and validation implementation. Use only operations needed by supported convergence paths. Broad lifecycle authoring stays deferred under DEFER-000001, not its shared storage dependencies. |
| `src/harness/element_artifacts.py`, `element_artifact_*.py`, `element_identity_bundle.py`, candidate/source/reference adapters; `evidence_inventory.py`, `spec_lexicon_gate.py`, `src/lexicon/source_contract.py`, `glossary.py` | Keep the exact-content validation required by supported producers. Additional formats and domains stay deferred under DEFER-000005. Existing callers already share some extracted validators. |
| `src/harness/squad_publication.py`, `squad_publication_snapshot.py`, `squad_source_*.py` | Keep existing publisher and authenticated source/recovery helpers for the accepted identity path. Do not replace Squad completion or duplicate publication ownership. Broader rollout stays DEFER-000004. |
| `src/harness/element_identity_legacy_guard.py`, `element_identity_state.py`, `squad_state.py`, `state_transaction_namespace.py`, Squad and CLI entry guards, rewind/retarget and projection-write guards | Keep protections together with the authority. Positive managed execution is missing; registration must not be used as a substitute for that integration. Do not remove guards to make a blocked managed run proceed. |
| `src/echelon/spec_graph_memory.py`, `spec_graph_structure.py`, `spec_graph_re.py`, `spec_graph_values.py`, shared memory audit/extraction helpers | Retain shared code now called by existing graph/memory paths. These are not all optional leaf modules despite their origin in deferred work. Preserve current-path behavior with regression tests. |
| `src/echelon/spec_graph_captured.py`, `spec_graph_identity.py`, `mempalace_captured_audit.py`, `mempalace_captured_artifact_audit.py`, history traversal additions | Retain as reusable work; no broad activation or new history features. Bring in only the portions required to preserve references/history and safely publish the chosen managed path; record that dependency against DEFER-000002. |
| `src/harness/element_identity_admin.py`, `element_identity_history.py` | Retain standalone tooling; defer broader CLI exposure and conflicted-history adoption under DEFER-000003. Reuse authority initialization/audit/restore if required; do not build competing tools. |
| Existing design/checkpoint documents, fixtures and review records | Preserve provenance. The deferred register controls resumption; a historical checkpoint is neither live-integration proof nor authority for unrelated work. |

## Concrete dependency evidence

- `element_identity_legacy_guard` imports `IdentityStore`; Squad, CLI, rewind,
  retarget and workspace/memory paths import the guard or store errors. Even
  negative admission reaches the authority's module dependencies.
- A conservative static import walk from store/guard reaches 24 identity-family
  modules, including lifecycle, bindings, candidate previews, publication,
  snapshots, source storage and managed state. This includes function-local and
  type-checking imports: it is dependency evidence, not a claim that every API
  executes on ordinary startup.
- The store directly exposes candidate/history preview and publication APIs;
  publication storage also calls snapshot/overlay code. Removing history-shaped
  files just because historical browsing is deferred breaks that composition.
- `spec_graph.py` now calls `spec_graph_memory` and `spec_graph_structure`.
  These shared modules also consume captured-source types. Removing the captured
  implementation as a blanket group would affect the existing graph path.
- Static source import inspection found no importers for the standalone admin
  entry module or `spec_graph_captured`; captured artifact audit imports captured
  audit helpers but has no static source importer itself. A symbol search through
  source, runtime, prose, scripts and `pyproject.toml` found only definitions for
  the new top-level captured graph/audit entry points. This does not prove absence
  of arbitrary external/dynamic callers and does not authorize deletion.
- The existing schema is version 6. Reverting to an early allocator checkpoint
  would be a schema/API rollback, not a harmless way to retain only counters.

## Delivery phase: original work still to close

### User scope correction: legacy build entry is excluded

The user explicitly excluded legacy `echelon build` from convergence after the
documentation checkpoint. Do not alias it to `echelon delivery run`, migrate its
native command, or clean up its legacy orchestration recipe merely to satisfy
the earlier entry-point checklist. Preserve its current behavior and admission
guard. Earlier references below to public/native build migration are historical
scope, superseded by this decision.

Convergence now targets the active controlled `echelon delivery run` path and
the prose it actually consumes. The coordinator already bypasses the legacy
build prompt when `delivery_gate_controller` is enabled; its internal canonical
`echelon build` strategy label is not an invocation of the legacy CLI and does
not need renaming. Feature-off delivery still uses the legacy prompt; excluding
the legacy command does not authorize a default cutover or removal of that path.

Next acceptance work is the active controlled prompt/companion ownership audit
and remaining delivery integration evidence, followed by the separately gated
bundle/rollout milestone. Update ownership guidance only to describe verified
active behavior. No entry alias, additional controller or identity activation is
needed for this scope correction.

The existing focused regression
`test_coordinator_trial_does_not_load_legacy_manager_command` passed (1 test in
0.26s) after read-only inspection of the coordinator boundary. Only scope records
changed; no CLI/runtime/prose behavior or rollout setting changed.

The [original delivery design](superpowers/specs/2026-09-11-delivery-controller-ownership-design.md)
has implemented opt-in command loading, sequential slice gates and durable
recovery. Its original phase 4 remains necessary, not newly added scope:

- At the reviewed baseline, `select_delivery_task` explicitly rejected
  finalization-only dispatch. The completed-scope handoff checkpoint below
  removes that barrier without adding documentation production.
- The generic build command remains a MANAGER orchestration recipe, including
  invocation-specific sequencing, finalization and state-machine continuity.
- At the reviewed baseline, public build dispatch still resolves `echelon.build`
  through the generic skill route; the controlled delivery path is opt-in through
  `llm.features.delivery_gate_controller`.
- Ralph already owns documentation verification, but the controlled slice does
  not yet own the documentation production/finalization sequence.

Next work must close these original entry/finalization/ownership gaps using
existing controller and provider boundaries before declaring the initial prose
antipattern fixed. Do not remove active legacy prose before its executing
replacement is ready. Do not claim all original delivery work is complete merely
because the implemented opt-in slice passes its tests.

## Identity phase: required integration, not another foundation project

After delivery closure, connect the original discovery fixture to normal producer
allocation, isolated candidate review, accepted publication/completion, and durable
bounded repair. Extend that same tested path to all requested entity families.
Use the [deferred register](element-identity-deferred-scope.md) to record any
necessary lifecycle/projection/admin dependency. The missing producer protocol and
semantic handoff need explicit implementation decisions; they must not silently
become a second allocator/controller or a broader architecture.

## Active prompt ownership audit after legacy exclusion

The [2026-09-13 audit](findings/2026-09-13-controlled-delivery-prompt-ownership-audit.md)
confirms the six controlled delivery roles use neutral, step-bound contracts and
have no inlined phase companions. It also reproduces a remaining source-repair
feedback conflict: inner/visual/review-requested repairs still receive a legacy
completion-marker instruction alongside the controlled JSON-only contract.
Generic failure details are lost in that legacy formatter. Documentation repair
already uses structured evidence. Root AGENTS/CLAUDE ownership guidance is stale.

Separate active limitations remain visible: fulfillment refresh embeds a
model-sequenced mapper/judge workflow, and PR triage sequences diagnostic agents
in prose and reads their profiles from `.claude/agents`. Neither was migrated by
the controlled slice/documentation checkpoint. This audit does not prove they
can be replaced by a prose-only edit or authorize a subsystem rewrite.

### PR-triage Prosaic migration checkpoint (2026-09-13)

The separately approved PR-triage correction is now implemented on
`fix/delivery-controller-contract` and independently accepted through code commit
`602ee524` after task-level reviews and final cross-component review.
`ReviewLoopController` deterministically groups comments and sequences the three
neutral Prosaic diagnostic roles before one composition turn. A bounded,
descriptor-pinned read channel services exact host-validated read requests; the
roles receive no shell, network, write, dispatch, or publication operation. The
controller validates the complete allocated composition before exclusive
attempt-local staging, and the existing `ReviewArtifactPublisher` remains the
only canonical writer and recovery/journal owner.

The historical audit statement above remains accurate for its audited baseline;
this checkpoint supersedes only that PR-triage limitation. It does
not alter fulfillment, legacy build, default activation, installation, or
identity scope. Verification scripts external Claude and Codex CLI processes
while exercising the real facade, adapters, read boundary, controller and
publisher; no live provider, installed-bundle, migration, push or merge ran.

The pre-review affected batch passed 560 tests; subsequent review-fix suites
passed 77 and then 78 tests. These are distinct runs, not a repository-wide
success claim. The audit records the unchanged baseline policy-inventory failure
and the final review corrections.

### Controlled source-feedback checkpoint (2026-09-13)

The subsequently approved source/mixed-feedback correction and narrow ownership
guidance update are implemented locally and independently accepted after scoped
re-review. Ralph
replaces its generated legacy repair recipe with original context plus structured
failure/evidence data before the source roles are dispatched. The controller
contract retains execution restrictions and the single JSON result format.
New snapshots replay exactly; old pending source-repair snapshots require
reconciliation without rewriting their journal or resetting their allowance.
Documentation-only and feature-off contracts remain unchanged.

Verification and limits are recorded in the audit: 164 surrounding tests passed,
then 22 source-feedback and 13 legacy-feedback tests passed after the
coverage-contract refinement; the final reviewer-instruction correction passed
49 affected tests. Direct downstream probes labeled visual/review do not establish
production Phase 3 PR re-entry coverage. This is scripted-provider, bounded integration
evidence, not full delivery convergence or installed/live acceptance. Fulfillment,
remaining native-entry/prose work, rollout and installed-bundle acceptance remain
separate; no deferred identity feature was activated. Do not claim all active
delivery prompts are clean.

### Production PR-review re-entry checkpoint (2026-09-13)

The next bounded acceptance exercises the real coordinator, PR review loop,
neutral triage/composer, canonical publisher, Ralph and controlled role gates in
a temporary workspace. Its preceding controlled slice and retained journal are
real; the preceding authoritative verification checkpoint is seeded. It covers
only the newly published review evidence/task scope, an interrupted repair and
restart, independent gate blocking in all three modes, both provider facades,
and accepted-slice replay at the authoritative-verification entry boundary.

This exposed triage usage held only in coordinator memory: interruption during
repair lost that usage on restart. The opt-in coordinator now persists cumulative
usage before re-entry, preserving Ralph's existing baseline/delta accounting and
budget admission. No role prose, provider adapter, identity feature, fulfillment
flow or developer instruction file is changed. Feature-off accounting is unchanged.

These checks do not establish completion of the entire review-fix batch or its
post-verification PR effects. External coding backends, Prosaic inspection, and
Git/PR service interfaces are scripted. Authoritative verification is not given
a fabricated passing result; accepted-path testing stops at its invocation.
See the ownership audit for verification results. Installed/live acceptance,
rollout and the remaining ownership work remain separate.

### Fulfillment ownership design prepared (2026-09-13)

The user approved preparing the next migration design. The
[controlled fulfillment design](superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md)
proposes four independently testable phases: deterministic preparation, neutral
semantic full refresh, scoped completion/recovery, and Ralph integration. It
reuses the existing runner, deterministic writers, validators and provider facade;
there is no new COMMANDER or generic workflow engine. Legacy/direct-CLI behavior
remains separate. The design is awaiting user review; no fulfillment runtime
migration, rollout or implementation acceptance is claimed. Phase 1 is the next
implementation checkpoint after design approval.

## Verification and limits

The boundary review used Git deltas, source/caller inspection, and a static Python
import walk. No production code changed and no live provider ran. It is not a
proof that an extracted release patch builds or that the whole branch is ready.

Fresh delivery baseline at implementation HEAD `4223b46b`:
`220 passed in 47.26s` across `test_delivery_prompt`, `test_delivery_slice`,
`test_delivery_slice_runner`, `test_delivery_slice_recovery`,
`test_delivery_controller_integration`, `test_prosaic_execution_policy`,
`test_cli_harness_resume`, and `test_visual_ralph` under `tests/unit/`.
This verifies the tested implemented behavior, not the missing phase-4 paths,
live provider execution, or identity convergence.

### Delivery corrections after the baseline review

Implementation commit: `7811922a` (budget and raw-entry bypass corrections).

The focused review found a downstream-repair budget defect: reconstructed Ralph
started without an allowance, while same-process visual repair reused the
pre-build allowance. Five new cases reproduced improper successful dispatch:
four exhausted/one-dispatch-remaining cases across same/reconstructed controllers,
and a coordinator callback with current visual cost not yet in strategy state.
All five passed after the narrow correction. Ralph now derives remaining allowance
from the tighter caller/persisted ceiling and greater caller/persisted usage;
the callback supplies cumulative usage including the current visual check.
The existing journal retains the resulting ceiling across restart.

The first original phase-4 admission correction rejects raw Python CLI
`echelon build`, including `--fix/--failures`, when controlled delivery is enabled.
It rejects before prose loading or provider dispatch and directs the user to
`echelon delivery run`. It does not silently turn a raw provider call into a run
with worktree/commit/publication effects. Feature-off behavior is unchanged.
Both actual Typer entry tests failed with successful provider dispatch before
the change and passed afterward.

Verification (overlapping suites, not additive totals):

- Budget regression cases: 5 passed, 30 deselected.
- Surrounding delivery/recovery/visual/outer-loop selection: 132 passed,
  233 deselected in 16.59s.
- The original eight delivery baseline modules after the budget fix:
  225 passed in 48.48s.
- CLI policy module including new admission cases: 9 passed in 0.47s.
- CLI policy, public Typer CLI and delivery-controller integration modules
  together after both changes: 120 passed in 10.74s.
- Independent read-only review of both fixes: no remaining findings in those
  bounded changes; no duplicate test runs by the reviewer.

This does not close phase 4. Documentation/finalization production, native
provider entry/prose migration, default rollout, external-spec output ownership
and bundle verification remain. Provider support is an explicit rollout boundary:
enforced read-only review requires Claude or Codex and a supported host.
Do not silently enable the controller for unsupported providers
or change provider configuration to make a test pass.

The earlier Codex-only rollout question was resolved by explicit user direction
on 2026-09-13: Claude must also be supported. The bounded adapter work below
implements that requirement; it does not authorize default cutover or expansion
to other providers. The controller remains opt-in pending the remaining phase-4
work. No provider capability was inferred from identity-dependency approval.

No installation, migration, live provider run or full-suite rerun occurred during
these corrections. A tracked visual-test `latest.json` side effect was restored
to its original content after the tests; it is not part of the release change.

## Claude controlled-delivery support (2026-09-13)

Claude now consumes the same neutral `tool_write_scope_exclusive` contract as
Codex. No Prosaic role or workflow prose changed. Claude-specific permission
translation remains in its Python provider adapter:

- Exclusive reviewers receive only Read/Glob/Grep, with Write/Edit available
  only for declared output files. Unsafe permission bypass is suppressed even
  when approved for implementation. Missing host enforcement blocks dispatch.
- The macOS host sandbox makes the candidate/read roots nonwritable except for
  exact declared outputs. Enclosing read roots do not reopen forbidden control
  children. Real-process probes verify writes through symlinks are also denied.
- Nonexclusive implementation receives native approval for workspace edits and
  exact declared exceptions, not an output-only tool restriction. Shell access
  retains the existing host approval policy: no broad Bash approval or automatic
  unsafe bypass was added. Ralph still owns authoritative verification.
- Explicit scopes reject paths that cannot be represented safely in Claude
  permission rules. Calls without the explicit flag retain legacy behavior.

Test-first regressions exposed and then verified the native approval gap, missing
exclusive enforcement, and enclosing-root control-file read leak. Independent
review identified the native approval blind spot in the initial process stand-in;
the correction and follow-up review have no remaining concrete findings.

Verification: 462 tests passed in 18.73s across `test_ai_cli_backend`,
`test_llm_provider`, `test_claude_delivery_scope`,
`test_delivery_controller_integration`, `test_delivery_slice_runner`,
`test_delivery_slice_recovery`, `test_llm_tool_policy`,
`test_coverage_diagnostic`, `test_verification_diagnostic`, and
`test_squad_executors_journal`. This includes the actual host sandbox, provider
facade, response parser and controller with a scripted external process, covering
acceptance and exhaustion after three rejected implementation attempts. It is
not a live-model test or a full-suite rerun.

Installed Claude Code 2.1.236 help was checked for the adapter's flags; permission
semantics were checked against the [official Claude permission reference](https://code.claude.com/docs/en/permissions).
No global installation, workspace migration, provider configuration change or
live provider execution occurred. Live Claude/Codex smoke verification and the
remaining original phase-4 work are still outstanding; this does not close the
overall convergence plan or add support on hosts without the enforced boundary.

## Completed-scope verification handoff (2026-09-13)

The user accepted macOS-only enforcement for now and requested continuation.
Cross-platform enforcement remains deferred; both Claude and Codex are required
within the current supported host boundary.

The first finalization-routing checkpoint distinguishes a completed canonical
task scope from a blocked/unready one. Only DONE/DONE_WITH_CONCERNS tasks qualify,
and every dependency in their transitive closure must also be complete. Empty,
unknown, malformed, cyclic, degraded, deferred and blocked scopes do not qualify.
Other targets' unrelated open tasks are not silently selected.

For a fresh completed scope, the existing delivery runner returns a zero-dispatch
handoff to Ralph. It creates no fake task, updates no canonical progress and
claims no reviewed implementation. Ralph still executes authoritative verification
and its existing runnability, fulfillment, documentation and task gates. An
invalid documentation report therefore remains a failure, not delivery success.

Pending operation journals retain priority: editing task checkboxes cannot skip
unresolved reviews. A previously accepted operation replays through the existing
progress/checkpoint window; only an already-applied operation eligible for the
next iteration is retired on handoff. Its journal remains evidence, its last task
remains available for explicit repair, and replay does not double-charge tokens.
Cancellation still blocks the handoff. No journal schema or provider contract
changed, and the feature remains opt-in.

Tests cover direct runner and Ralph consumers, target isolation, incomplete
dependencies, cancellation, reconstruction, receipt retention and a full-loop
handoff into the real documentation gate before publication. That full-loop
fixture uses a scripted sandbox verifier and no Phase-A fulfillment service;
it is not live-model or end-to-end fulfillment acceptance evidence. Independent
read-only review found no actionable correctness or recovery findings.

Verification after the cancellation correction: 458 passed in 54.69s across
`test_delivery_slice`, `test_delivery_slice_runner`, `test_delivery_slice_recovery`,
`test_delivery_controller_integration`, `test_delivery_finalization`,
`test_ralph_inner`, `test_ralph_outer`, and `test_documentation_gate`.
The 12 new finalization cases are included in that total. The baseline was
125 passing delivery tests; six new handoff tests first failed on the missing
route, and a separate cancellation regression failed before its guard was added.
This is a focused regression gate, not a full-unit-suite or live smoke claim.

This closes only verification-only routing for already-completed scopes.
Controller-owned documentation production/repair, report publication/recovery,
native entry/prose migration, default rollout and bundle smoke checks still
remain before original phase 4 can close. No installation, live execution,
identity activation or cross-platform expansion is included.

## Documentation execution helper checkpoint (2026-09-13)

Commits `b7e9967a` and `f3146044` add the bounded documentation helper beneath
Ralph. TECH WRITER may edit only candidate README/CHANGELOG; DOCS VERIFIER has
read-only scope. Both return dispatch-bound report values. Python runs existing
deterministic validation and publishes the canonical report pair only after
independent review passes. The helper reuses delivery journal locking and atomic
storage, persists the three-author-attempt ceiling, rejects unknown dispatch
completion, and recovers partial publication from exact before/after images.
It returns no completed task IDs and does not authorize delivery acceptance.

Independent review found and fixed two defects before integration: ignored,
untracked documentation now participates explicitly in candidate identity, and
canonical task/report inventories no longer inherit a 50-finding array limit.
The focused re-review approved both fixes with no remaining findings.

Evidence: one surrounding regression batch passed 242 tests across documentation,
durability, delivery selection/runner/recovery and both provider boundaries.
Subsequent validator and reviewed fixes passed 67 documentation cases; their
RED tests reproduced the defects before the corrections. No full-unit run,
installation or live provider execution is claimed. Full-tree streamed hashing
adds filesystem cost on dependency-heavy candidates; publication uses pinned
atomic replacement with before-image checks, not a kernel-level compare-and-swap
against an uncooperative concurrent writer.

Ralph routing/report-preservation integration follows in the
[documentation checkpoint plan](superpowers/plans/2026-09-13-delivery-documentation-controller.md).
This helper alone does not close original phase 4 or activate identity features.

## Documentation operation integration checkpoint (2026-09-13)

Commit `9c474d63` routes a nonempty documentation-only failure set to the helper.
Source and mixed failures retain implementation repair. The existing operation
pointer distinguishes documentation from task work; restart dispatches its saved
kind and original inputs before selecting new work. Unknown completion and
changed failure evidence require reconciliation rather than fresh attempt
budgets. Accepted documentation does not complete task IDs or replace the last
real implementation task used for source repairs. Cumulative usage is charged
only as an unseen delta.

Controlled documentation gates now require an independent report even for a
no-impact declaration and never rewrite the independently reviewed report pair.
Legacy default-false behavior remains unchanged. Runnability selection checks
the current stack/contract and immutable receipt; the runner owns initial
candidate validation and subsequent exact-content replay checks, so the author's
own documentation edits do not incorrectly invalidate recovery.

Consuming tests cover all modes, complete and partial task scopes, source/mixed
routing, internal/external specs, publication/progress crashes, changed inputs,
receipt-backed reconstruction, token accounting, and the real inner verification
loop. Initial integration RED was 25 failures; later RED cases caught changed
feedback, recomputed changed-file inputs and overstrict receipt replay.

The surrounding batch had 761 passing tests and two existing test-double
signature failures. After those narrow fixture corrections and the receipt
recovery fix, the affected-file run passed 438 tests, including all 41 new
integration cases. Unaffected passing files were not rerun; this is not a
repository-wide test or live-provider claim.

**Initial independent integration review: needed fixes; the checkpoint was not accepted.**
The real post-verification chain reruns runnability after documentation authoring.
README/CHANGELOG changes alter the product fingerprint and therefore the new
runnability evidence digest. The independent docs report still cites pre-authoring
evidence, so the gate correctly rejects it and the accepted-operation guard
correctly refuses to reuse its approval. The passing inner-loop fixture has no
enabled runnability contract; the receipt-backed recovery fixture deliberately
ends at the repair limit. Neither proves this positive convergence path.

Subsequently approved sequencing correction: add a
controller-owned checkpoint after authoring and before independent docs review
to obtain current runnability evidence. Preserve Ralph ownership, the existing
operation and attempt ceiling, and exact evidence comparison. Do not weaken
digest comparison, silently refresh canonical report hashes, reuse stale approval,
or ignore README/CHANGELOG changes in product/evidence identity. A positive
real-loop regression with runnability enabled is required for acceptance.

Remaining original delivery work: public/native entry routing, active
prose/companion migration, default rollout decisions, and installed-bundle
acceptance. Deferred identity integration is still a separate milestone.
No installation, live execution, migration, push or default activation occurred.

### Approved sequence, additional report-identity blocker

The user approved the post-authoring runnability refresh. Reproduction before
implementation then exposed a second issue for in-worktree specs: publishing
`documentation-impact-report.md` and `docs-verification-report.md` changes the
same product fingerprint used by runnability evidence. The verifier report cites
evidence whose digest includes the report itself. Refreshing earlier alone
cannot remove this circular dependency.

Two consuming RED cases in `test_delivery_documentation_checkpoint.py` reproduce
the real-loop stale-evidence block and the post-authoring/publication fingerprint
change. They use real Git checkpointing, report generation and validation, with
external provider/sandbox execution scripted. Both failed in 2.12s. No production
code or identity policy was changed during that reproduction-only checkpoint.

Separately approved additional policy: exclude only the two resolved
canonical controller-owned documentation report paths from the runnability
product fingerprint, keeping their independent validation and exact publication
checks. README/CHANGELOG remain product content. This does not authorize broad
spec/report exclusions, rewriting report hashes after review, or a new inventory
framework.

### Approved correction implemented and independently accepted

Commit `782f58a7` implements both approved corrections. Runnability identity
excludes the exact two reports at the resolved spec location; general product
inventory and other evidence fingerprints remain unchanged. README, CHANGELOG,
source and other spec inputs remain covered. The existing runnability producer,
documentation consumer and Land comparison use the same narrow policy.

After each successful authoring attempt, Ralph refreshes runnability through its
existing execution owner before independent review. The same documentation
journal records checkpoint intent/completion and retains original evidence.
Final verification may reuse only that reviewed, fully published checkpoint,
after checking the actual candidate, current stack/contract, receipt integrity
and currentness, and exact report bytes. Unknown or failed completion blocks;
the operation, three-author ceiling and cumulative accounting are unchanged.

Verification: 86 focused checkpoint/integration tests passed, followed by one
surrounding batch of 942 tests passing without failures or warnings. The cases
include both neutral provider facades in all three modes, real enabled-runnability
loop convergence, restart boundaries, failed/cancelled refreshes, mutation
rejection, budget/attempt limits and Land's archived candidate comparison.
External providers and sandbox execution are scripted; this is not live-provider
or installed-bundle acceptance. Independent scoped re-review found the original
failure addressed and no new Critical/Important breakage. This closes Task 2 and
the documentation repair checkpoint. The positive real-loop fixture disables
fulfillment refresh; it does not establish broader phase-4 or whole-branch merge
acceptance. Remaining native entry/prose, rollout and bundle milestones above
are unchanged; no deferred identity feature was activated.
