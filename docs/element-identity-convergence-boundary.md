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
remains separate. The user subsequently approved the design; the
[Phase 1 implementation plan](superpowers/plans/2026-09-13-fulfillment-preparation.md)
specifies shared preparation steps, explicit run binding and compatibility
acceptance. No fulfillment runtime migration, rollout or implementation acceptance
is claimed. Phase 1 is the next execution checkpoint.

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

## Inactive fulfillment preparation checkpoint (2026-09-14)

Commits `a4c963f0` and `8c1694b0` implement Phase 1 of the
[controlled fulfillment design](superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md).
Existing deterministic preparation writers and their CLI state/degradation
semantics now share narrow helpers. A separate callable validates an explicit,
already initialized source/spec/run/scope context and executes the fixed
preparation order. It preserves full canonical inventories and exact legacy,
six-digit and seven-digit IDs in both full and scoped preparation. It rejects
unsafe/mismatched inputs and existing semantic artifacts; it does not select a
new run, reset lifecycle state or publish fulfillment success.

Final affected acceptance: **285 tests passed in 8.31s**, including 60 consuming
sequence cases and 26 shared-step cases. A missing-input CLI exit-code regression
was reproduced and fixed before commit. Real writers, parsers, topology receipts
and a real managed Git worktree were exercised with scripted external graph
executables. The independent read-only review found no introduced
Critical/Important defects. Scope search found no new sequence call from Ralph,
`FulfillmentRunner` or the standalone spec CLI. The existing CLI uses only the
extracted step helpers. See the
[executed plan](superpowers/plans/2026-09-13-fulfillment-preparation.md)
for exact test gates and limits.

This is an inactive preparation checkpoint, **not closure of fulfillment
orchestration ownership or original phase 4**. Neutral semantic mapping/judgment,
full/scoped completion, recovery/publication/usage accounting, Claude/Codex
provider acceptance and delivery cutover remain later phases. Existing observer
option precedence and managed-worktree admission were reused, not redesigned.
No provider adapter, Prosaic role, AGENTS.md/CLAUDE.md, legacy build flow, mode
policy or identity activation changed. No installed-bundle refresh, live model
run, graph installation, push, merge or branch-wide verification was performed.

## Approved inspection-boundary prerequisite (2026-09-14)

Phase 2 admission inspection confirmed the existing generic Codex review
profile enables network and does not disable shell/agent tools. Its read-only
filesystem capability is not the stronger inspection capability required by
fulfillment. No runtime change was made during that inspection.

The user approved a scoped provider-boundary checkpoint, then approved reusing
PR triage's tool-disabled model turns and Python-serviced bounded reads through
neutral interfaces. The
[recorded design](superpowers/specs/2026-09-14-host-serviced-inspection-design.md)
and [implementation plan](superpowers/plans/2026-09-14-host-serviced-inspection.md)
define this prerequisite. The original fulfillment design now records the
amendment so future work does not revert to generic `run_agent_result` or invent
a second native read-tool policy.

### Implemented and independently accepted

Commits `1bf7ec12`, `80c67750` and `bcedd7f3` expose neutral optional no-tools
turns for both Claude and Codex and extract the bounded reader with host-named
roots and explicit denied paths. Native execution controls remain in the existing
adapters. Triage retains its old constructor, policy, limits and semantics.

Final affected acceptance: **728 tests passed in 29.34s**, including 15 composed
cases with scripted model processes and real adapter preparation, capture and
host reads. Claude's emitted macOS sandbox was also actually exercised against
direct source reads/writes; Codex controls were checked in emitted commands.
This is not live-provider, installed-bundle or whole-branch acceptance.

Six case/Unicode alias regressions and ten macOS firmlink regressions were first
reproduced, then fixed. Denial combines conservative normalized path components
with filesystem-identity anchors, including listings and separately named roots.
Independent review found the firmlink defect; focused re-review confirmed the
fix and reported no remaining findings. Cross-read immutable evidence binding
remains future workflow work, not a guarantee of this reader.

This closes only the inspection prerequisite, not Phase 2 or original phase 4.
Neutral semantic roles, their host controller and subsequent recovery/publication
and delivery cutover remain deferred to their approved checkpoints. No active
fulfillment caller, Prosaic content, AGENTS.md/CLAUDE.md, legacy build flow,
mode/default or identity policy changed. No installation, live model call, push
or merge occurred; the convergence branch/worktree is retained. Provider API
transport remains necessary and distinct from prohibited model network tools.

## Controlled fulfillment implementation closure (2026-09-14)

The user requested completing all remaining implementation phases before live
testing. The [executed completion plan](superpowers/plans/2026-09-14-controlled-fulfillment-completion.md)
closes the semantic, full/scoped, recovery and Ralph integration phases of the
[approved fulfillment design](superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md).
This supersedes the inactive-fulfillment limitations in the earlier checkpoints,
not their historical receipts or the deferred identity register.

With the existing `llm.features.delivery_gate_controller` opt-in, Python now
owns fulfillment preparation, mapper/prepass/optional-judge sequencing, exact ID
validation, scoped merge, publication, lifecycle and usage accounting. The two
neutral roles load through Prosaic and use the accepted host-serviced inspection
interface for both Claude and Codex. Semantic receipts bind inputs and admitted
reads; completed work is reused without redispatch or duplicate charging.
Unknown completion and conflicting edits block rather than resetting the run.
Controlled caches and verified ledgers carry their own semantic-profile contract
identity, which the coordinator now preserves in its immutable checkpoint.

The real completed-PR-fix acceptance found that publication recovery rejected
host-authored task completion. Completed journals now admit only exact replay
of the existing DONE formatter for their own batch IDs. Definitions, unrelated
tasks and review artifacts remain bound; incomplete publication stays exact.
Passing fulfillment permits the existing post-verification effects once;
nonpassing fulfillment leaves them untouched in guided, semi and banzai modes.

Mode policy, banzai refresh deferral, default activation, observer authority,
owner deferrals and exact legacy/six-digit/seven-digit IDs remain unchanged.
Feature-off delivery and standalone verify-spec retain their command-driven
contracts. No AGENTS.md/CLAUDE.md, legacy build entry or deferred identity
activation changed. The controlled prompt audit found no legacy COMMANDER,
generic phase execution or native provider-agent lookup in the new path.

Final affected acceptance: **1,251 tests passed in 164.38s**, plus **18 task
progress tests passed in 0.24s**. Independent scoped reviews reported no remaining
findings after RED reproductions and corrections; `git diff --check` passed.
The completion plan records the phase receipts and exact evidence limitations.

This is controlled-fulfillment implementation acceptance, not completion of the
separate identity integration or release milestones. External model processes,
graphs, verifier execution and PR services are scripted in the composed tests.
No installed-bundle refresh, live provider/game run, installation, push, merge
or branch-wide merge verification was performed. The convergence branch and
worktree remain in place; the recorded bundle/live/merge gates must still be
completed before treating this as real-use release acceptance.

## Discovery-first integration design checkpoint (2026-09-14)

After controlled-fulfillment implementation closure, the user approved proceeding
with discovery-first identity integration. The
[written design](superpowers/specs/2026-09-14-managed-discovery-integration-design.md)
proposes two semantic producer turns around host reservation, independent
candidate review, and guarded publication through existing Squad completion.
Its first proving slice covers U/A creation and same-subject repair only; it
does not unlock unsupported managed phases or change public/default activation.

The existing discovery-candidate and graph/publication composition suites passed
**102 tests in 13.22s** at `0db43e2a`. They remain characterization evidence, not
proof of positive managed Squad execution. This checkpoint changes only design
and scope records. The written design awaits user review before implementation
planning; no source code, stopped smoke workspace, installation or live provider
was changed.

### Inactive discovery contract checkpoint

The user approved the written design and inline implementation. The
[executed contract plan](superpowers/plans/2026-09-14-discovery-producer-contracts.md)
now provides closed proposal/author/review replies and pure translation into
existing candidate artifacts and create/revise requests. Prosaic owns two new
neutral profiles; Python owns assignment validation and materialization.
Existing candidate/history preview remains the structural authority, and cannot
be replaced by a translated descriptor or model verdict.

Final affected acceptance: **551 tests passed in 28.36s**, including 94 new
tests and real temporary SQLite candidate consumption. Both profiles passed
actual Prosaic inspection without deployment. Independent review found no defects
and exercised fresh U/A creation across all six output artifacts. Whitespace
checks passed. This does not establish durable reservation binding, provider
execution, semantic approval, managed Squad admission or publication/completion.

Next is the approved durable operation/reservation/provider-turn checkpoint,
then Squad publication/recovery and bounded repair acceptance. No live workspace,
installation, public/default activation, legacy SCOUT, AGENTS.md/CLAUDE.md or
legacy build changed. The existing branch/worktree remains the execution home.

### Inactive discovery reservation-binding checkpoint

The next durable checkpoint was split at its independently testable allocation
boundary. The
[reservation plan](superpowers/plans/2026-09-14-discovery-reservation-binding.md)
now retains canonical proposals and complete per-kind reservation intents before
allocation, then exact mappings before returning to the caller. Unchanged keys
retain their subjects and IDs across proposals, including removal/reintroduction;
new keys alone allocate new ranges. No Markdown or retained references are rewritten.

Completed mappings use a new read-only lookup on the existing identity store.
Missing completed receipts fail without reallocating; interrupted pending
reservations recover the exact request. The selected-run journal authenticates
already registered managed genesis and its retained source context, rejects
changed selection/scope/source and requires explicit creation versus resume.
Its checksum is corruption detection, not semantic or controller authority.

Final affected acceptance: **613 tests passed in 41.45s**, including **63 new
tests**. Tests use real SQLite, captured source manifests, guarded source-head
advance and the existing candidate preview. They exercise interruptions before
and after allocator commit and journal writes, permanent associations, forged
receipts, missing authority, path/link/lock rejection and unchanged accepted
history/artifacts. Independent read-only review found no defects; whitespace
checks passed.

This is only the reservation part of the approved durable checkpoint. The caller
must durably select the operation under existing execution leases before explicit
journal creation. Managed bootstrap, provider intents/results/usage, semantic
execution and Squad integration remain next. The three-proposal receipt ceiling
is not a substitute for persisting attempts before provider dispatch. No provider,
publication/completion or rollout path is activated by this helper.

### Inactive discovery selection/bootstrap checkpoint

The [bootstrap plan](superpowers/plans/2026-09-14-discovery-bootstrap.md) connects
fresh-spec enrollment to the existing SquadStateStore. Protected transitions
retain the independent selected spec/run/operation, namespace and sealed capture
marker, then the original empty source manifest, then the exact genesis receipt.
Generic state writes cannot inject, alter or remove bootstrap metadata. Pending
selection blocks legacy Squad entry before any registry enrollment; actual run
and single-phase entry tests cover guided, semi and banzai without provider calls.

The inactive helper opens established authority, uses the existing guarded source
inspection and source/genesis registration APIs, and confirms durable state at
each handoff. It never initializes a missing registry. Interrupted registrations
replay exact requests; completed state authenticates retained rows rather than
recreating missing ones. Source drift, namespace/selection changes, conflicting
registrations and missing/corrupt recovery material block. The component test
feeds completed bootstrap into the actual reservation journal and preserves its
first `U-000001` reservation across resume.

Independent review found one Important ordering defect: completion was written
before the source inspector's final exit validation. Two failing regressions
reproduced this after each real database registration. Completion now follows
successful inspection exit; failed validation leaves captured state and retained,
idempotently recoverable registrations. No findings remain. This confirms the
bootstrap capture, not future provider-input freshness or publication authority.

Final acceptance: **848 affected tests passed in 34.08s**, including **63 new
bootstrap tests**; **397 existing managed/Squad exclusion tests passed in
184.31s**. Whitespace checks passed. Existing Phase A/run leases remain caller-
owned and are real in the component tests. No positive Squad discovery admission,
provider execution, allocation inside bootstrap, accepted candidate publication,
installation, default change, live smoke or merge occurred.

Next is bounded provider-turn intent/result recovery and accounting, followed by
semantic execution and guarded Squad publication/completion/repair integration.
Runtime admission must still prove the absence of unsupported RE/external-memory
domains and capture the complete selected provider inputs. The original approved
discovery-first scope and existing branch/worktree remain unchanged.

### Inactive discovery provider-recovery checkpoint

The [provider recovery plan](superpowers/plans/2026-09-14-discovery-provider-recovery.md)
adds receipt-backed execution of one selected discovery semantic step through
the existing no-tools inspection interface. Both provider selections use the
same neutral Prosaic producer/reviewer profiles and host-serviced read boundary.
It does not introduce provider-specific prose, native agents lookup or COMMANDER.

The reservation journal's secure file/lock handling is shared without changing
its schema or allocation behavior. Protected Squad state selects the provider
receipt journal before initialization; a missing selected journal blocks instead
of resetting accounting. Pending intents, replies/usage, serviced reads and
checked final results are saved separately. Recovery never repeats an uncertain
call or returns a final reply whose post-response checks were interrupted.
Completed results replay with cumulative usage, not an additional charge.
Unknown usage is explicit; token/dispatch ceilings only tighten across resume.

Role loading and model dispatch share the persisted absolute step deadline;
verification and receipt-write delays cannot launch an expired call or accept
an expired reply. Independent review demonstrated deadline gaps, each reproduced
before correction. The final re-review found no remaining substantive findings.
Final affected acceptance: **1,096 tests passed in 76.20s**, including **68 new
discovery-turn tests**. Whitespace checks passed. The checkpoint plan records the
exact command, fault reproductions and test boundaries.

This remains an inactive component checkpoint. Scripted model responses exercise
real state, files, reads and SQLite authority; the new tests do not prove actual
provider-facade or live execution. Accepted artifacts and registry history remain
unchanged. Existing execution leases, complete input/domain capture, semantic
ordering, candidate approval, durable repair units and Squad publication/completion
remain the integrated caller's next work. A nine-step defensive receipt ceiling
does not implement the three-attempt repair policy.

No positive Squad discovery admission, installation, live game run, default/mode
change, migration, push or merge occurred. The stopped smoke workspace, provider
adapters, neutral role contents, AGENTS.md/CLAUDE.md and legacy build are untouched.

### Inactive reviewed discovery candidate checkpoint

The [reviewed-candidate plan](superpowers/plans/2026-09-14-discovery-reviewed-candidate.md)
joins the existing pieces: a protected operation and attempt transition in
SquadStateStore, captured spec/input/template bytes, proposal, permanent
reservation association, authoring, structural preview and independent semantic
review. The helper returns a bound reviewed candidate; it does not publish it.

Each attempt is consumed durably before its proposal turn. There are at most
three attempts, with early stop on repeated normalized findings and candidate
content. Label/whitespace churn alone cannot reset progress. Rejected candidates
retain reservations and IDs across retries. Malformed, uncertain and stale-cited
provider results block rather than entering an automatic protocol-repair loop.
Candidate citations name exact artifact bytes and definitions; additional source
citations must name captured input bytes. Templates use the existing runtime
files and are part of the fingerprint, not new prose or provider-specific paths.

Read-only accounting observation preserves known provider charges even if an
unrelated source/template/reservation failure prevents resumption. Every attempt
uses the detached selected request, including nested origin/findings. Both defects
were reproduced during independent review before their corrections. Missing
already selected journals intentionally require reconciliation, even across
initial setup interruption; absence never selects a fresh budget or allocation.
Final independent re-review found no remaining blocking findings.

Acceptance: **1,734 affected tests passed in 87.50s**, plus the final **41
composition tests passed in 18.85s** under actual Phase A/run execution leases.
The suite scripts external Prosaic inspection and model replies, not the source,
state, reservation, preview or history owners. A guarded fixture publication
establishes a real accepted question; the proposed clarification reaches revision
2 while accepted revision 1 stays untouched. Subject reassignment rejects before
review, and fresh U/A definitions retain distinct six-digit family counters.

The runtime owner still must establish complete configured input/domain admission,
authenticate this result at existing guarded publication and Squad completion,
and recover those effects before stopping at an unsupported next phase. This is
one selected operation within the existing bootstrap, not general selection of
subsequent accepted repair units or activation of other producers. Returned
artifacts include read-only dependencies, not an unrestricted publication list.
Actual provider-facade and managed guided/semi/banzai acceptance remain open.
No installation, live game run, public/default change, push or merge occurred.

### Discovery runtime input-admission checkpoint

The [runtime-input plan](superpowers/plans/2026-09-14-discovery-runtime-inputs.md)
extends the existing composed operation's source inspection with canonical
configuration, optional constitution, run-local context/evolution and knowledge
files. These join spec, input and template bytes in one authenticated capture.
Selected request, mode, autonomy, stack and calibration state enter the same
immutable operation fingerprint. All existing turn/replay checks reobserve them;
absent optional files becoming present also invalidate the selected review.

Configuration remains host-only, not model context. The host validates the actual
MemPalace wing selection and requires the RE root to be absent; it does not read
an external collection or recursively acquire an RE domain. An existing `re`
directory blocks even if no publication is registered. `ignore_re` or a claimed
absent RE state cannot conceal one. A configured memory wing remains unsupported
even with a made-up `enabled: false` key: the existing memory owner does not use
that key to disable retrieval. No new configuration switch is introduced.

The admitted context is the existing five-file generated local context set, with
an exact empty memory reconciliation and empty feature registry for the selected
request. Linked prior/WIP feature identities, additional context domains,
structured product-input packages, polyrepo targets and retarget operations stop
before attempts, reservations or calls. These are exclusions for this internal
fresh proving slice, not claims that those Echelon features are unsupported in
legacy execution or removed from convergence scope.

Admitted documents become read-only reference candidates and exact reviewer
source citations, never writable outputs. Changed configuration/context/state
blocks resume while retaining known provider accounting. Pre-checkpoint operation
fingerprints cannot be upgraded or reset silently; they require reconciliation.
An empty registry is not enough to establish document provenance: independent
review reproduced an old foreign ID in retained context attaching to a newly
allocated same-spelled local ID. The existing reference parser now screens every
new runtime document, blocking identity-bearing/invalid reference context before
allocation. No foreign identity provenance is inferred. The pre-existing explicit
spec-scoped input-tree contract is unchanged.

Positive Squad admission, typed evidence/investigation-domain selection, guarded
publication with a bound graph/history/review, durable completion/release and
recovery before the unsupported next phase remain open. This checkpoint does not
replace those owners or grant an internal candidate publication authority.

Final affected acceptance: **1,800 tests passed in 119.14s**, including 66 new
input-admission cases. The tests exercise actual state, source capture, identity
storage and candidate checks; external Prosaic/model processes are scripted.
Both provider IDs and all three autonomy modes are covered at this component
boundary, not through positive managed Squad dispatch or live provider facades.
Final independent review found no outstanding Critical or Important issues and
independently passed 107 focused tests in 66.33s. Previous-run evolution selection
remains a later caller duty; this checkpoint only captures the current run-local
optional document and never infers a prior run.

### Reviewed discovery publication preparation

The [preparation plan](superpowers/plans/2026-09-14-discovery-publication-preparation.md)
connects the retained accepted operation to the existing sealed publication and
captured graph owners. It replays checked proposal/author/reviewer receipts,
stages exact selected UTF-8 outputs with retained file modes, projects those
images over proposed identity history and seals the resulting source-plus-graph
package. Every sealed operation must match the expected target, action, bytes
and mode; self-consistent staging alone does not establish reviewed content.
A second graph projection and final role/receipt/source checks protect the
handoff. Neither a supplied candidate nor a completion-ID string is authority.

The identity source claim deliberately stays spec-only: registration fixed that
selection at genesis. A separate complete source snapshot guards the spec,
explicit input tree, templates, config, optional constitution, context, knowledge
and evolution inputs. The proposed version-3 request retains that full snapshot
in its recovery document while using the registered spec baseline for its source
claim. Do not widen registration or later promote with only the spec snapshot.
Memory is reported unavailable/not configured after real input admission, never
as a successful collection audit. No external memory or RE collector runs.

Host-only replay checks at the existing operation, provider-step and reservation
owners forbid creation, new attempts, provider steps and reconstruction of missing
or incomplete reservation receipts. Unbound staging retries use fresh transaction
IDs without model calls, reservations or rewriting accepted provider receipts.
Ordinary interrupted-operation recovery is unchanged. Existing pending identity
or Squad publications/completions and product-input mutations block reselection.
Preparation never promotes canonical
bytes, applies identity changes, advances source heads or completes a phase.

Guarded promotion is tested only with explicit temporary fixture authority.
Production still needs a durable authenticated association to the existing Squad
completion owner, guarded promotion/application, effect recovery and final release.
It must recover pending work before rejecting the next unsupported producer.
The returned recovery document is data for that association, not a shortcut around
it. Subsequent repair selection must also admit the already-published derived
graph through its existing owner; this helper does not select a new operation.
Positive runtime admission, rollout and live-provider acceptance remain open.

Final affected verification: **3,000 tests passed in 197.06s**, including all
40 preparation cases. Independent review reproduced and helped close the
pre-seal byte/mode binding gap and unnecessary replay receipt rewrites, then
independently passed the 40-case suite in 59.82s with no outstanding Critical or
Important issues. These receipts do not establish positive Squad admission or
live-provider readiness.

### Reviewed discovery bound to existing completion

The [completion-binding plan](superpowers/plans/2026-09-14-discovery-completion-binding.md)
extends the existing external-publication completion envelope with a closed,
versioned managed-discovery association. It retains the exact v3 identity request,
complete source snapshot, and canonical inputs behind the existing candidate and
source digests. Protected accepted operation/bootstrap/provider state authenticates
those inputs; a supplied recovery document or hash alone grants no authority.
The ordinary external-publication format remains unchanged.

The existing completion drain now uses guarded source publication for this
association: prepare the identity intent before promotion, apply it only after
verified source/graph postimages, then drain existing completion effects. Both
stages survive handoff and durable completion until identity release. Restart
can finish release from the existing completed-dispatch receipt, including a
crash after publication-stage cleanup. Orphan cleanup cannot discard managed
recovery material or report readiness while that material remains unresolved.
No new journal, allocator, publication loop or completion state machine is added.

Context generation has an explicitly approved captured-input path in the existing
builder. The existing completion generator callback receives only the selected
reviewed artifact postimages, not live staging/canonical/WIP discovery. It renders
their current-context snippets with the existing size limit, preserving the
fresh pre-spec five-file/schema contract and empty feature/memory records. This
is not general feature/memory admission. Legacy context generation is unchanged.
The context receipt's preimages must match the reviewed capture; partial installs
accept only those originals or their receipted replacements, and later steps
require the replacements. All other captured sources remain pinned through
completion and release. Callback preparation respects publication-before-completion
lock ordering; generation consumes detached bytes inside the completion boundary.

This connects the **existing completion owner**, exercised under real execution
leases with scripted external processes. It does not yet enable managed entry
through normal `SquadController.run`, select the next repair operation, run an
unsupported next producer, install a bundle or establish live-provider readiness.
The saved next phase is preserved. Positive managed admission must recover this
bound work before rejecting unsupported dispatch, without weakening legacy
exclusion. Existing unbound recovery-v1 preparation packages lack the new digest
preimage proof; prepare a fresh checked association, never rewrite pending
identity authority or reconstruct missing provider/reservation receipts.

Final affected verification: **3,120 passed in 409.61s**, including all 50
managed completion tests and 17 context-builder tests. The full Squad integration
suite finished with **507 passed and 7 pre-existing failures in 411.66s**; each
failure was also reproduced against the prior checkpoint and expects entry past
the existing managed legacy-execution guard. No new failure appeared. Their exact
names and disposition are retained in the plan, not hidden by deselection.
Independent final review passed 21 targeted tests in 58.44s with no actionable
findings. This is an offline local checkpoint, not installed/live acceptance.

### Normal-entry integration and checkpoint contract (2026-09-14)

The [normal-entry plan](superpowers/plans/2026-09-14-discovery-normal-entry.md)
now connects explicit internal selection to normal Squad entry, real graph
routing, reviewed publication and completion recovery. Six-artifact discovery
passes scripted Claude/Codex and guided/semi/banzai checks, and stops before
`phase1-synthesizer`. The seven obsolete managed-legacy guard expectations are
reconciled. Read the plan for exact verification scope and remaining checks.

The approved checkpoint extension preserves the existing Git writer and ledger
location. Its sealed parent, completion identity, exact committed artifact bytes
and receipt authenticate the fresh ledger image. Full source capture is retained;
only exactly authenticated metadata is projected out of the spec identity view.
The existing identity release payload retains that proof after temporary staging
is removed. This is fresh-discovery support, not a blanket exception for arbitrary
control files or existing ledgers. Later repair must reuse the checked projection
and retain full source guards; it must not invent another ledger or rewrite heads.

Accepted-baseline repair and full producer coverage remain required. No public
activation switch, installation, migration or live-provider acceptance is claimed.

### Accepted-discovery retention for repair (2026-09-14)

The user approved extending the preceding checkpoint so every new discovery
release retains full completion proof, not only releases with a Git checkpoint.
The [repair retention plan](superpowers/plans/2026-09-14-discovery-repair-retention.md)
records the version-3 payload and exact version-1/version-2 cleanup compatibility.
Old payloads stay immutable; version 1 cannot authorize a new repair by having its
missing proof reconstructed. Version 2 retains its checkpoint-only interpretation.

Protected repair selections and attempt records now have their own namespace in
the existing Squad state owner; original discovery state and receipt paths are
unchanged. The existing secure receipt-file owner supports isolated repair-unit
paths. Finding order cannot create a new unit, changed instructions conflict,
and unresolved work cannot acquire a second origin/budget. Saved-state validation
enforces those cross-unit restrictions as well as normal transitions.

This checkpoint does not yet select an authoritative requesting review or dispatch
repair turns. Runtime admission must authenticate the exact origin and accepted
source, preserve graph/context/evidence provenance, bind the selected unit to the
existing operation/provider/publication/completion owners, and return to the
requesting phase. The original renumbering/evidence end-to-end acceptance remains
open. No new controller, allocator, migration or live activation is introduced.

### Accepted-discovery repair input capture (2026-09-14)

The [repair input plan](superpowers/plans/2026-09-14-discovery-repair-inputs.md)
connects the selected repair baseline to the existing coherent source inspector.
The reader authenticates accepted artifact/graph/checkpoint images against retained
completion proof, and generated context against the same completion's context
receipt. Original context is used only for the existing fresh-domain checks;
consumers receive the verified current context. The full raw capture, including
graph and checkpoint metadata, remains in the fingerprint and freshness guard.
No file is regenerated, no ID is reallocated and no attempt or provider receipt
is consumed by this reader. Fresh creation and unsupported-domain guards remain.

This closes accepted-source admission only. The protected selection's `review_id`
is still an association, not an authenticated requesting-review occurrence.
Managed intervening producers and WHY1 are not enabled. Runtime integration must
bind that real review origin, per-unit provider/reservation receipts and bounded
attempts to the existing guarded publication/completion owners and exact return
route. The original renumbering/evidence repair acceptance and full activation
remain open; this read-only checkpoint must not be presented as either.

### Managed Synthesizer integration (2026-09-14)

The approved [Synthesizer plan](superpowers/plans/2026-09-14-managed-synthesizer.md)
extends normal managed Squad entry through the next real producer. The optional
internal `through_phase: phase1-synthesizer` selection permits this checkpoint;
the existing selection remains discovery-only by default. Synthesis publishes
its seven required Markdown outputs and updated derived graph, then stops at
the unchanged `phase1-modeler` successor without dispatching later producers.

The same proposal/reservation/author/review, Prosaic inspection, publication,
completion and checkpoint owners perform the work. A closed producer selection
chooses a neutral synthesis role and separate protected state/receipt paths.
Original discovery bootstrap, operation, provider receipts and released proof
remain immutable. New U/A use the existing counters; existing IDs, subjects,
captions and revision-bound evidence are not renumbered or repurposed.

The earlier checkpoint limitation is now extended for this authenticated second
checkpoint only: the proof reader validates the captured prior ledger and exact
append while the existing writer still owns Git and ledger publication. Pending
append recovery requires the prior ledger to remain present. Historical parent
proof authenticates captured discovery images after the child advances the live
identity head. Raw metadata and generated context remain in the guarded capture;
only receipt-verified derived context is excluded from duplicate definition
parsing, not from model evidence or freshness checks.

Read the plan for test/review results. This checkpoint does not activate Modeler,
Tracker, WHY1, review-origin selection or repair execution. The original
renumbering/evidence repair acceptance remains open. No public/default activation,
installation, workspace migration or live-provider readiness is claimed.

### Intent identity prerequisite (2026-09-14)

The approved [intent identity plan](superpowers/plans/2026-09-14-intent-identities.md)
adds UI (explicit user intent) and II (inferred intent) to the existing identity
authority before managed Tracker integration. Allocation, replay, lifecycle,
candidate publication history and reference assessments use the same owners.
New numeric IDs have at least six digits and no maximum width; imported spellings
remain exact. The detached `intent` source role recognizes only the two existing
Tracker table layouts. Malformed definitions reject; row edits cannot silently
renumber, reclassify, delete or repurpose identities. Graph projection exposes
distinct UserIntent/InferredIntent nodes with retained history and assessments.

No database schema changes or saved-record rewrites are introduced. UI/II-looking
text now participates in reference validation; previously ignored text may require
explicit reconciliation, never automatic adoption. An older binary that lacks
these families cannot open a registry containing them. Matching deployed code and
reviewed source admission remain rollout prerequisites.

This is an identity prerequisite, not Tracker execution or full activation.
The current managed path is greenfield, where the native workflow skips Modeler;
managed Tracker, ALIGNED/DRIFT/STOP_AND_ASK handling, retained producer-source
continuation, WHY1 and authenticated review-triggered repair still require their
own tested integration. Discovery remains U/A-only; default selection, provider
dispatch, installation and the stopped game workspace are unchanged.

### Detached clarification preparation (2026-09-15)

Task 1 of the approved [managed Tracker plan](superpowers/plans/2026-09-15-managed-tracker.md)
separates reconciliation rendering from the legacy filesystem wrapper and adds
immutable clarification candidates from captured decision records, exact receipt/
policy preimages and Markdown text. It reuses existing policy derivation and
reconciliation semantics; source requirements and their IDs are never rewritten.
Exact latest-decision retry returns identical output, conflicting history rejects,
and new decisions append without replacing earlier records. Markdown receipt text
is not parsed as decision authority. Unproven legacy receipt/policy files require
explicit reconciliation, not automatic adoption.

This is preparation only. No managed resolver, live context generation, decision
admission, Tracker round, publication or routing is enabled. The existing legacy
execution exclusion remains intact. The following integration must authenticate
the records against the human-input owner, guard all captured images, publish
through the current transaction/completion owners and retain each Tracker round.
The two initial normal Tracker acceptance cases still fail at unsupported managed
selection and remain uncommitted integration work; they are not covered by the
passing preparation checkpoint. Full Tracker integration and activation are open.

### Retained context ancestry prerequisite (2026-09-15)

The next partial Task 2 checkpoint extends the existing completion proof reader,
not the producer or human-input admission surface. After Discovery and Synthesis,
original runtime-domain admission now follows the entire retained context chain
instead of rolling back only one generated context. Every parent is selected by
its exact completion association; accepted artifacts, identity history and context
must match the child's captured before-images. Traversal is iterative and rejects
repeated operations. Full source captures and model evidence stay current; the
projection neither writes original context back to disk nor discards read guards.
Old version-2 checkpoint proof bytes remain unchanged and incomplete legacy proof
cannot authorize continuation.

This verifies ancestry for the two integrated producers only. It does not enable
Tracker, create a resolved clarification, retain Tracker rounds or publish answers.
Those remain approved work in the same plan, followed by WHY1/review-origin repair
and the original renumbering/evidence acceptance. Default managed selection,
provider abstraction, legacy managed-execution guards and installation are unchanged.

### Tracker semantic/candidate contract (2026-09-15)

The approved Tracker plan now includes its inactive version-3 reply contract.
UI/II proposals and revisions feed the existing identity authority; exact labels,
immutable subjects and historical evidence survive statement revisions. Required
intent and optional stakeholder outputs are distinguished: absent optional output
does not create an empty file or authorize deletion. Authored ALIGNED/DRIFT/
STOP_AND_ASK metadata is bound into the review assignment; it grants no routing or
automatic-answer authority. Discovery/Synthesis encodings remain unchanged.

This is a Task 3 dependency for Task 2's real answer/re-entry acceptance, not a
new capability beyond the approved plan. Execution remains closed. Retained
Tracker rounds, exact routing through receipt/candidate/completion proof, native
Modeler skip and guarded clarification publication remain pending. The two normal
Tracker acceptance cases are still RED. See the existing plan for test evidence;
no installation, migration, live-provider run or activation is claimed.
