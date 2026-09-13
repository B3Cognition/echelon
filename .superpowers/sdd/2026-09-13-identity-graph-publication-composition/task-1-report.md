# Task 1 implementer report

Status: DONE. No native production gap or failing fixture was encountered.

## Scope and starting state

- Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
- Branch: `fix/delivery-controller-contract`.
- Original BASE: `88e5af8122067fb75c7b0207fc2aa2f77eb881a3`.
- Read the exact task brief first, then the complete implementer template and applicable repository/testing/verification instructions. No whole-plan or unrelated-ledger reads, child agents, reviewer dispatches, production edits, public APIs, live services, global installations, main mutations or stopped-smoke edits.
- Root's `progress.md` was already dirty and remained outside all scoped staging and commits. Root owns the plan/brief/progress.
- This is explicitly authorized characterization of existing APIs. There is no contrived missing-API RED and no production implementation phase.

## Implemented behavior

Created `tests/unit/test_identity_graph_publication_composition.py` (542 lines, 17 collected cases) and added one 78-line section to the existing large `docs/element-identity-storage.md`; no existing tests were edited.

The fixture creates real isolated on-disk identity authority, reserves string `FR-000001`, parses exact typed old/new requirement bytes and materializes revision 1 with immutable subject `Movement`. The old evidence file contains `See FR-000001.\n`; its actual native parsed reference is independently checked at `span:4:13`, relation `evidence`, then stored at revision `"1"`. Evidence is read-only in the candidate/publication scope, not claimed to be OS-immutable. The selected tree also contains hidden binary bytes and an empty directory, and initially has no graph.

Two immutable native transactions have distinct literal IDs. The provisional source-only transaction is never promoted, unsealed, reused as a mutable prepared transaction, or given an identity intent. Native assembly/preview, source-image projection, canonical planning using actual projected bytes and their correct artifact hash, and captured graph assembly run before creating the final transaction. The supplied audit is an explicit deterministic `composition-test-wing` observation. Policy explicitly includes the evidence file.

The final transaction seals exact spec and graph bytes as ordinary writes. Candidate assembly explicitly classifies the graph as a physical opaque write, with normal typed spec/evidence bindings. A second real coherent preview uses the same unclaimed revision operation. The final projected manifest contains graph bytes, and graph rederivation equals the complete actual graph postimage bytes despite that additional selected file. Independent graph assertions check the stable `req:demo:FR-000001` key, current revision `"2"` and retained claim's `ASSESSES_REVISION` edge to revision `"1"`. SQL dumps prove previews do not change state.

The real final initial source manifest is registered explicitly for this existing assessed fixture. The exact required v3 request ties the final marker, original encoded source baseline, exact child payload and complete proposed history hash. Actual intent preparation precedes promotion. The actual publisher owns both physical artifact promotions in native sorted order; no test assumes spec-before-graph. A short fixture hook only calls actual journal application after physical promotion. No graph construction/write, provider or planner runs in that hook.

Successful assertions cover complete physical source images and modes, retained evidence/binary/empty directory, projected/final source manifest equality, complete applied/reopened history payload equality, exact canonical application receipt payload, full source association and sequence `"1"`. Actual SQL rows remain one reservation, one entity, two revisions, one retained historical claim, one source publication and one identity intent. Exact apply/release retries compare receipts and complete SQL dumps without another reservation. Release happens only after successful guarded return and final assertions, with an explicitly fixture-only string; reopened retained release state/request/completion are checked.

Cases added after reporting the first real test outcome:

1. Native fault positions 0, 1 and 2: before first promotion, after first operation, and after all operations before identity apply. Actual partial files follow `promoted_prefix` and retained operation order. Original request/baseline, stages, old history, registration source head and unapplied source plan remain pending. Conflicting actual reserve/lifecycle writes fail. Reopen/reload uses the persisted request and baseline codecs and finishes the exact same operation.
2. Hook failure immediately after successful actual identity apply. Complete physical postimages and source head are present, but guarded publication raises; applied journal stays pending. Idempotent actual application during recovery returns the same receipt before successful guarded exit and release.
3. One spawned real child receives only a project path and bounded event, reopens persisted state and calls actual publication. At the first completed promotion boundary it signals and executes `os._exit(73)`, bypassing Python unwinding. Parent waits/joins with bounds, checks the deliberate distinct exit code, reopens real state and recovers the exact partial prefix from retained material. There are no sleeps or stress loops.
4. Eight actual preflight drift variants after identity preparation: evidence bytes, hidden binary bytes, evidence file mode, empty-directory addition, empty-directory removal, changed canonical preimage, corrupted graph-stage bytes and graph-stage mode. Native `target_drift`/`stage_corrupt` occurs before even the pre-publish hook, hence before the actual apply hook. Full inventories and pending database state remain unchanged by failure handling; no recovery material is discarded or drift repaired.
5. Post-apply hook changes evidence. Native post-hook checks reject the guarded call while actual application remains committed and pending. Reopen/retry from the original retained baseline also rejects the drift before actual apply retry. Complete SQL state/inventory is unchanged by that failed recovery, source sequence remains `"1"`, and conflicts stay blocked. No release occurs.
6. Real stale-history preparation rejection after an actual independent import changes complete retained history without consuming the revision child ID. Separately, real stale-source preparation rejection after a native no-op sealed publication advances the same source context while preserving identity history and physical source manifest. Both reject before retaining the attempted original intent; complete SQL dumps show rollback/no mutation.

## Actual run, failure, correction and tree chronology

All test commands below ran from the stated worktree using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`. No setup test suites were run. Output was pristine, with no warnings or errors.

### Run 1: first actual end-to-end composition only

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_identity_graph_publication_composition.py::test_sealed_graph_and_sources_match_applied_identity_history -q
```

Output:

```text
.                                                                        [100%]
1 passed in 1.15s
```

The first version was the new happy-path test and its native fixture/assertion helpers. It passed on its first actual run. No fixture correction and no expectation weakening occurred. Its genuine outcome was sent to root before adding any interruption/rejection cases. This pre-staging working-tree version did not receive a separately recorded tree ID.

### Run 2: expanded new module

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_identity_graph_publication_composition.py -q
```

Output:

```text
.................                                                        [100%]
17 passed in 7.59s
```

This was the first run after adding all interruption, child-process, source/seal drift, post-apply drift and stale-history/source-head cases, plus prepared-state SQL assertions. All cases passed immediately. Root was notified. This pre-staging version did not receive a separately recorded tree ID.

### Self-review amendments before the covering run

No failures required correction. Reading the diff identified worthwhile assertion/clarity improvements: use the exact native dataclass types in the fixture carrier; compare the complete stored application receipt string to canonical JSON, not only its decoded object; assert retained release state/completion/request; and place actual journal application behind the preflight/recovery rejection tests' apply hooks so reaching a hook would exercise the real effect. Added the storage documentation section describing measured behavior and remaining boundaries.

Staged only the new test module and storage documentation. `git diff --cached --check` passed with no output. Exact staged tree before the six-module run:

```text
aea329a8e2bdc415f1743bfc7a08e05c9f3f11c1
100644 6eb3afa1bd7c899bab21d118c0ef903ae0796fda tests/unit/test_identity_graph_publication_composition.py
100644 87f135e3a193c05a55de5c4c2b66e54cf115c368 docs/element-identity-storage.md
```

Root's independent dirty progress file was the sole tracked unstaged difference from this tree; it is not executable test input. All production and six covering-module code matched this staged tree.

### Run 3: six requested covering modules, once

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_identity_graph_publication_composition.py tests/unit/test_squad_source_guard.py tests/unit/test_element_identity_publication_history.py tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_candidate_preview.py tests/unit/test_spec_graph_captured.py -q
```

Output completed at 100%:

```text
451 passed in 31.80s
```

No test or documentation content changed during or after this run. `git diff --cached --check` passed again and `git write-tree` still returned `aea329a8e2bdc415f1743bfc7a08e05c9f3f11c1` immediately before commit.

Scoped commit:

```text
dcebb085cbb88e4557e14a0944a5614e2e1dad51 test: characterize sealed graph and identity publication recovery
tree aea329a8e2bdc415f1743bfc7a08e05c9f3f11c1
2 files changed, 620 insertions(+)
```

This report is the only subsequent implementer amendment and is retained separately as administrative evidence. It does not change tested code or storage documentation. No unchanged postcommit tests, full-unit, capacity, live, global-install or extra covering-suite repeats were performed. There were no initial fixture failures, hidden failing runs, production fixes or weakened contracts.

Administrative staging initially returned exit 1 because `.superpowers` is ignored: `The following paths are ignored by one of your .gitignore files: .superpowers`. That stopped the chained administrative commit before any commit occurred. The task explicitly authorizes retaining this exact report, so staging was corrected to `git add -f` for this report path only, followed by the named administrative `git diff --cached --check` and separate commit. Root's progress/plan/brief were not staged. This was not a test failure or a tested-source amendment.

## Native versus fixture-only boundaries and self-review

Real native functions own identity allocation/materialization, parsed references, candidate observation, request/baseline validation, graph projection/rendering, immutable sealing, filesystem/source guarding, actual artifact promotion, durable journal application, accepted source-head advancement, conflict rejection and exact retries. SQL reads/inventories are observations, not substitute mutation authorities or validators.

Fixture-only ownership includes source selection, the two-transaction staging arrangement, deterministic audit observation, graph comparison expectations, hook placement, sequencing and opaque recovery/completion strings. This is not a production gate, semantic approval, authenticated complete dependency/memory acquisition, prospective storage pass, managed enrollment/migration, run ownership, pending-read enforcement, controller/squad completion, producer/manual/CLI integration or bounded repair. The low-level publisher is not claimed to reject freshly sealed semantically wrong graph bytes. Future production ownership must provide final graph rederivation, semantic authorization and closed recovery admission. No rollout is authorized.

Self-review read both scoped diffs and checked that native functions own every effect/rejection claimed, that every filesystem case explicitly requests the existing secure-POSIX capability fixture, that original evidence remains at revision 1, that preview never runs against pending identity authority, and that actual partial captures are observations rather than replacement recovery baselines. The single test module is intentionally shared-fixture characterization at the specified file path; the existing large storage document received only the focused new section. No production gap or unresolved correctness concern was found. Root still owns the fresh original-BASE independent review.
