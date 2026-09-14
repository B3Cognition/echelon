# Managed discovery completion binding implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, test-driven development and independent read-only review. Do not delegate implementation.

**Goal:** Bind the reviewed publication into the existing durable Squad completion intent, preserving recovery material until identity release.

**Architecture:** Extend the existing external-publication envelope with an optional versioned managed-discovery request. Authenticate its candidate/source digest preimages against protected discovery state, and use the existing guarded publisher and identity intent APIs. Keep normal runtime admission disabled; recovery is exercised through the existing completion owner under execution leases.

**Tech Stack:** Python, Squad completion/outbox/state, guarded source publication, SQLite identity store, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`; narrow persisted completion-format extension explicitly approved by the user after checkpoint `cd31ba88`.

## Constraints

- Existing worktree/branch only; no installation, migration, live calls, public activation, push or merge.
- No provider-specific prose/adapters, AGENTS.md/CLAUDE.md, legacy build or stopped smoke workspace changes.
- Existing external publication records without the extension retain their exact format and behavior.
- Preserve the registered spec-only source baseline separately from the complete guarded read set.
- A supplied hash or recovery document is not authority. Check digest preimages against the protected accepted operation and selected bootstrap/provider binding.
- Retain publication and completion stages through identity release; restart must recover a completion finalized immediately before a release interruption.
- No new publication/completion engine, journal, allocator or public mode. Positive managed Squad entry and next-phase dispatch remain excluded.

## Task 1: Closed completion association and authentication

Files: `discovery_operation.py`, `discovery_publication.py`, new `discovery_completion.py`, `squad_completion.py`, `squad_state.py`, tests `test_discovery_completion.py`.

The external publication remains `{kind: external, marker: ...}`; managed discovery adds `managed_discovery: {version: 1, request: <canonical v3 request string>}`. The request's recovery document retains candidate and source fingerprint preimages, not a new authority. Existing operation digests remain unchanged.

- [x] Test a real accepted operation and publication through completion sealing/reload; assert the exact v3 request and full read set survive, legacy records stay identical, and malformed/mismatched IDs, sources, operations, graph, review or digest preimages reject.
- [x] Expose canonical preimages already hashed by discovery. Add them to the prepared request without changing fingerprint/candidate digest algorithms or saved operation state. Decode with existing strict JSON and snapshot/request codecs.
- [x] Validate the optional envelope in the completion owner and authenticate it against protected selected discovery state and routed completion provenance before any managed recovery action. Reject missing associations on managed runs and managed associations on legacy runs.

```python
completion = prepare_bound_completion(real_reviewed_run)
loaded = load_prepared_controller_completion(root, run, completion.marker)
assert loaded.intent.publication["managed_discovery"]["request"] == encoded_request
assert not canonical_outputs_exist()
```

## Task 2: Existing owner publication, effects, release and recovery

Files: `discovery_completion.py`, `squad.py`, `squad_state.py`, tests `test_discovery_completion.py`.

- [x] Install the real routed completion via existing prepared-result/routing-decision state APIs in fixtures. Call the real drain under Phase A/run locks, with scripted provider replies only.
- [x] Branch within the existing external publication owner: managed records use `publish_sources(full_snapshot, before=prepare_identity_publication, after=apply_identity_publication)`. Authenticate the exact request/marker/source/history association on each recovery, including partial promotion.
- [x] Preserve the publication stage after handoff. Require applied identity/source postimages before completion effects. Let existing completion receipts own authorized context changes; do not require the old context after its completion effect.
- [x] After durable controller completion, validate its retained dispatch receipt, release the matching identity publication idempotently, then discard stages. Recover an interrupted release from the completed dispatch and retained completion stage before cleanup. Keep public legacy admission guards unchanged.
- [x] Fault-inject before/after identity preparation/application, partial promotion, handoff, completion and release. Assert no provider redispatch, duplicate lifecycle changes, premature release or lost recovery material. Changed sources/history/stages/association block.

```python
outcome = controller._drain_pending_controller_completion()
assert outcome.recovered
assert store.identity_publication(spec_id=spec_id, operation_id=publication_id)["state"] == "released"
assert state.load()["last_dispatch"]["post_dispatch_complete"] is True
```

## Task 3: Review and checkpoint

- [x] Run affected discovery, source/graph/identity publication, completion/state and Squad integration/exclusion regressions.
- [x] Independent read-only review; fix concrete findings with red-green regressions.
- [x] Record exact evidence and remaining positive admission/provider/repair scope in convergence documents.
- [x] Commit locally and preserve branch/worktree; no activation, merge or push.

## Implementation and approval-boundary history

This local checkpoint implements the optional completion association, original
candidate/source digest preimages, guarded publication, retained staging,
identity release and completed-dispatch recovery. Fault tests
closed loss of recovery material after stage cleanup and premature orphan cleanup.
The managed context receipt now must bind its preimages to the reviewed context;
partial installation permits those preimages or the exact receipted postimages,
and later steps require the postimages. Other captured inputs stay pinned.

Independent read-only review found an additional blocker: the existing default
`build_run_context` reads canonical/run-local spec trees and run staging that are
not in the selected discovery read set. Merely passing empty memory drawers does
not constrain those reads. A new staging Markdown file containing `U-999999`
after sealing enters completed context, and identity publication releases.
`test_completion_cannot_import_uncaptured_staging_into_context` reproduced this
failure before the approved extension below.

The proposed decision was to add a captured-input path to the **existing context
builder**, invoked via the completion owner's existing generator callback. It
must derive context only from the authenticated reviewed/projected source set,
without live filesystem discovery, external collection, new admitted domains,
a second context writer, or changes to legacy callers. Define the exact context
projection before implementation. Do not silently freeze old context, broaden
capture, clear staging, or skip the completion effect to pass the test.

The user approved that extension. Its bounded projection is:

- Add optional `captured_discovery_artifacts: dict[str, bytes] | None` to
  `build_run_context`. The caller authenticates a fresh local discovery selection
  and supplies only selected reviewed artifact postimages, keyed by canonical
  project-relative path. Reject empty/invalid mappings, non-UTF-8/NUL content and
  nonempty drawers before writing. No fallback to live discovery on invalid input.
- Render current context with the run ID and sorted selected artifact snippets,
  using the existing 3,000-character per-artifact limit. This refreshes actual
  reviewed content, not a copy of stale generated context. Do not include the
  derived graph, read-only dependencies or unrelated staging files as artifacts.
- This fresh pre-spec projection has no feature metadata yet. Preserve the
  existing five-file/schema contract: empty prior feature context, empty feature
  registry lists for the retained request, empty memory reconciliation and its
  existing stale-memory report. Reuse captured drawer reconciliation with no
  drawers; do not discover or invent external feature/memory observations.
- `discovery_completion` supplies the existing completion generator callback
  after authenticating applied identity/source state. Select bytes from the exact
  projected spec snapshot and selected artifact paths. The callback invokes the
  existing builder with captured data and the completion owner's private output
  directory. Receipt creation/install/replay/release remain with existing owners.
- Test ambient canonical/WIP/staging files, no filesystem-read fallback,
  malformed captured data, actual selected U/A text in resulting context, and
  interrupted context installation. Rerun legacy builder tests unchanged.

```python
projected = project_publication_source_images(binding.sources)
artifacts = {item.path: item.content for tree in projected.trees
             for item in tree.files if item.path in selected_artifact_paths}
generator = functools.partial(build_run_context, captured_discovery_artifacts=artifacts)
# Existing prepare_or_load_completion_context owns generator invocation,
# staging, durable receipts and recovery; the builder adds no journal.
```

Evidence so far (not a final acceptance receipt):

- Initial completion association/promotion tests: 5 passed, including Claude and
  Codex IDs with three scripted inspection calls and no redispatch.
- Fault/recovery and drift batch before the final review fixes: 31 passed in
  106.08s. Tampered request and partial-promotion batch: 13 passed in 30.72s.
- Context pre/postimage and orphan-cleanup review fixes: 5 passed in 20.07s.
- State kernel: 256 passed in 2.73s.
- Existing completion + entire Squad integration: 732 passed, 7 failed in
  384.35s. All seven failures reproduced by loading the three previous-HEAD
  modules directly from Git into memory, without modifying the checkout:
  `test_managed_identity_prepared_initialization_survives_controller_fresh_start`
  (three modes), `test_managed_identity_manual_replay_preserves_metadata_before_simulated_dispatch`,
  and `test_managed_identity_manual_updates_reject_injection_before_provider_dispatch`
  (three injected managed cases). These expect entry past the pre-existing
  managed legacy-execution guard. Keep the guard; reconcile the old expectations
  separately from granting positive managed runtime admission.

Version-1 unbound publication recovery packages
lack the new preimage proof; prepare a fresh association through checked replay,
never upgrade a pending identity publication or reconstruct missing receipts.

The captured extension then exposed a publication/completion lock inversion in
the first wiring attempt. Preparation of its authenticated detached callback now
happens before acquiring the completion lock; the ordered managed context effect
requires that callback and never falls back to live generation. The six targeted
completion cases passed in 23.62s after correction. Independent final re-review
reported no actionable findings and passed 21 targeted tests in 58.44s, covering
both context drift boundaries, ambient staging/canonical/WIP exclusion, invalid
captured input, snippet limits and partial context installation without generation
on restart. Legacy context-builder tests remain unchanged and pass alongside the
new captured branch.

## Final verification and checkpoint

The final affected suite passed **3,120 tests in 409.61s**, including all 50
managed completion cases and 17 legacy/captured context-builder cases. The command
used the existing Echelon virtualenv Python with `-m pytest -q --tb=short` and
these exact selections, from the existing delivery-controller-contract worktree:

```text
tests/unit/test_discovery*.py
tests/unit/test_element_identity_candidate*.py
tests/unit/test_element_identity_legacy_guard.py
tests/unit/test_element_identity_publication*.py
tests/unit/test_squad_source*.py
tests/unit/test_squad_publication*.py
tests/unit/test_identity_graph_publication_composition.py
tests/unit/test_spec_graph*.py
tests/unit/test_controller_lock_order.py
tests/unit/test_squad_completion.py
tests/unit/test_durable*.py
tests/unit/test_inspection*.py
tests/unit/test_host_serviced_inspection.py
tests/kernel/test_squad_state.py
tests/unit/test_context_builder.py
tests/unit/test_context_reconciliation*.py
tests/integration/test_element_identity_publication.py
```

The complete `tests/integration/test_squad_controller.py` run finished with
**507 passed and the same 7 pre-existing failures in 411.66s**. No new failure
appeared; the seven prior-HEAD reproductions and their exact names are recorded
above. This is not an all-green repository claim. Their reconciliation remains
separate from enabling managed runtime entry.

Independent final review: **21 targeted tests passed in 58.44s**, no remaining
actionable findings. Whitespace checks passed. The original namespace/counter,
provider abstraction and legacy admission boundaries are preserved. Local
checkpoint only: no installation, migration, live provider spend, public/default
activation, push, merge or worktree cleanup. Normal managed Squad admission and
subsequent repair/producer selection remain the next integration work.
