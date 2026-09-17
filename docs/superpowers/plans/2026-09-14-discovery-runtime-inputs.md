# Discovery runtime input admission implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, as requested by the user. Use test-driven development and an independent read-only review.

**Goal:** Prevent a reviewed discovery candidate from omitting the real runtime context or silently ignoring configured RE/external-memory dependencies.

**Architecture:** Extend the existing discovery operation's sealed source inspection, not the publication engine. Capture fixed runtime context/configuration sources in the same inspection as selected artifacts and inputs. Bind the relevant run-state inputs and complete captured manifest into the existing immutable operation fingerprint; revalidate at every existing turn/replay boundary.

**Tech Stack:** Python, existing Squad source snapshots/state, SQLite identity store, pytest; scripted external Prosaic/model processes only.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`

## Global constraints

- Keep the existing worktree/branch; no installation, migration, live calls, public activation, push or merge.
- Neutral Prosaic roles and both Claude/Codex remain unchanged.
- No edits to AGENTS.md, CLAUDE.md, legacy build or the stopped smoke workspace.
- The fresh proving slice admits no linked RE, external-memory retrieval, polyrepo target or structured product-input package. Establish those exclusions from captured configuration, observed RE-root absence and selected state, not supplied empty graph arguments.
- This checkpoint closes input admission before publication integration. It does not positively admit Squad execution, select subsequent operations, collect new domains, publish, or complete a phase.
- Existing pre-checkpoint operation fingerprints cannot be silently upgraded or reset. Changed input contracts require reconciliation.

## Task 1: Capture and enforce runtime inputs at the existing operation boundary

**Files:** Create `src/harness/discovery_inputs.py` and `tests/unit/test_discovery_inputs.py`; modify `src/harness/discovery_operation.py` and the fixture in `tests/unit/test_discovery_operation.py`.

**Interfaces:** The new pure selector returns fixed project-relative runtime trees/files. Its admission function consumes `PublicationSourcesSnapshot`, root/run paths and actual selected state; returns a detached state-context dict and read-only text dependencies. `_capture` includes these paths in its existing `inspect_sources` call, authenticates on normal exit, and includes the state projection in its fingerprint. Existing `run_discovery_operation` remains the entry point; there is no optional bypass flag.

- [x] Add consumer tests showing required context/constitution/knowledge files arrive in every semantic turn, configuration secrets do not, and context/config/state changes block replay without extra calls.

```python
result = execute(prepared, executor, create=True)
assert result.status == "reviewed"
assert executor.calls[0]["context"]["runtime"]["user_message"] == "Create an isometric game"
assert executor.calls[0]["context"]["evidence"][".echelon/constitution.md"] == "# Constitution\nLocal-first game.\n"
```

- [x] Add admission failures for missing/malformed/duplicate config, configured memory wing, actual RE content, changed RE selection, redirected/missing context, active structured product inputs/targets and symlinked captured paths. Assert zero allocations/turns/attempts on initial failure.

```python
(root / ".echelon/config.yml").write_text("mempalace:\n  wing: enabled\n")
assert execute(prepared, executor, create=True).status == "blocked"
assert "managed_discovery_operation" not in state.load()
assert executor.calls == []
```

- [x] Run the new tests and confirm failures expose missing admission/capture.
- [x] Implement fixed runtime selection: run-local `context`, `knowledge-base`, `re`, canonical config and optional constitution. Require the existing five generated context outputs and validate the reconciliation report; absent constitution/knowledge sources remain observed absence. Bind selected user request, mode, autonomy, calibration and stack context. Reject unsupported configured domains without reading external memory or calling legacy writers.
- [x] Include admitted documents as read-only reference candidates and reviewer source citations; retain raw config only in the host capture/fingerprint, never model context. Preserve exact selected input content and runtime state across callbacks/replay.
- [x] Run focused tests, then all discovery/source/state/exclusion regressions. Inject context/config/state drift during model calls and check usage is retained and no accepted attempt is saved.

## Task 2: Review and close the checkpoint

- [x] Independent read-only correctness/scope review while running affected verification; fix proven defects with regression-first tests.
- [x] Update convergence boundary and deferred register with exact tested scope and remaining publication/completion work. Do not label this positive runtime admission or real-use readiness.
- [x] Verify diff and tests, commit this checkpoint, retain the worktree and branch.

## Baseline

126 discovery operation/provider and graph/publication composition tests passed in 28.17s at `ef5215f2`; worktree initially clean.

## Implemented boundary and verification receipts

The RE root is selected as a single missing-path observation. If it is a
directory, the existing regular-file inspector rejects it without recursively
collecting the unsupported domain. This deliberately also rejects an initialized
but unpublished RE layout. The run context must have exactly the existing five
generated files and no nested domains. There is no new context generator.

The six later feature-registry regressions showed that required-file presence
alone admitted malformed, stale-request and foreign-feature context. An exact
empty registry bound to the selected request is now required. Cross-spec typed
identity association remains unimplemented; references from another feature are
not guessed to belong to this spec. This constraint belongs to the fresh internal
proving slice, not to legacy context construction or public configuration.

- Initial guard tests reproduced missing model context and admission/drift checks;
  the nine state-selection cases were corrected to use the real state path and
  rerun red before implementation. **87 input/operation tests passed in 57.89s**.
- The six feature-registry cases failed before the new registry check. Added six
  scripted provider-ID/autonomy combinations for Claude/Codex × guided/semi/banzai.
  **99 input/operation tests passed in 69.94s** with these checks.
- Before the registry check, the affected discovery, source, publication, identity
  candidate, state, lease, durability and inspection suite passed **1,780 tests in
  117.19s**. This is not a full-branch or live-provider test run.
- Independent review reproduced foreign IDs in a context document despite an
  empty feature registry. Six regressions (prior/current/stale context, knowledge,
  constitution and evolution) failed before the correction. Every newly captured
  runtime document is now screened by the existing `references` adapter; parsed
  references or diagnostics require provenance not admitted by this checkpoint.
  The existing explicitly selected spec-scoped input-tree contract is unchanged.
  These six cases plus context/config/state changes during a provider turn passed
  **9 tests in 2.20s**, with zero initial allocation or retained 7-token/1-call
  accounting for interrupted admission, respectively.

The real runtime still must select/authenticate typed evidence/investigations,
admit the supported Squad entry, and bind candidate/graph/history/review to the
existing guarded publication and completion/release owners. Current documents are
read-only reference context, not verification evidence claims or publication
targets. No managed execution has been activated by this input checkpoint.

Final affected verification: **1,800 tests passed in 119.14s**, including all
66 input-admission cases and the existing 41 operation cases. Whitespace checks
passed. Independent final review found no outstanding Critical or Important
issues and independently ran **107 focused tests in 66.33s**. Current run-local
evolution capture matches this plan; selecting a previous run's evolution report
remains the later positive runtime caller's duty, not an inferred latest-run
lookup. Exact affected command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest \
  tests/unit/test_discovery*.py tests/unit/test_element_identity_candidate*.py \
  tests/unit/test_element_identity_legacy_guard.py tests/unit/test_squad_source*.py \
  tests/unit/test_squad_publication*.py tests/unit/test_identity_graph_publication_composition.py \
  tests/unit/test_controller_lock_order.py tests/unit/test_durable*.py \
  tests/unit/test_inspection*.py tests/unit/test_host_serviced_inspection.py \
  tests/kernel/test_squad_state.py -q --tb=short
```
