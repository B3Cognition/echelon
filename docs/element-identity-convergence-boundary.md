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

The [original delivery design](superpowers/specs/2026-09-11-delivery-controller-ownership-design.md)
has implemented opt-in command loading, sequential slice gates and durable
recovery. Its original phase 4 remains necessary, not newly added scope:

- `select_delivery_task` explicitly rejects finalization-only dispatch.
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
the existing enforced read-only review capability currently requires Codex and
a supported host. Do not silently enable the controller for unsupported providers
or change provider configuration to make a test pass.

Default cutover is paused for a user decision: should the first converged release
remain opt-in and Codex-only, or also provide enforced controlled review for the
other currently supported build providers? The latter requires provider-boundary
work beyond the currently implemented trial. No compatibility reduction or new
provider capability was inferred from approval of necessary identity dependencies.

No installation, migration, live provider run or full-suite rerun occurred during
these corrections. A tracked visual-test `latest.json` side effect was restored
to its original content after the tests; it is not part of the release change.
