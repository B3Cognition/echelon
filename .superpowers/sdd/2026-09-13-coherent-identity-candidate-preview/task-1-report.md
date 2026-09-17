# Task 1 implementer report

Status: DONE. Implementation and verification complete. Scoped commit: `24186d390b2473531ea223f51d05d4cea7f460e0` — `feat(identity): preview candidates and exact journal history coherently`.

## Scope and implementation

- Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
- Branch: `fix/delivery-controller-contract`.
- Original BASE and pre-change HEAD: `48b9d3caf5e3fb545cdfedf9888a4c4ec41d5a76`.
- Exactly four scoped files: new `src/harness/element_identity_candidate_preview.py` (87 lines), thin method/type annotation in `src/harness/element_identity_store.py` (23 added lines), new `tests/unit/test_element_identity_candidate_preview.py` (762 lines), and `docs/element-identity-storage.md` (67 added lines).
- The frozen result uses the existing candidate-check and history class identities. Operations are detached with `validated_operations`, decoded with `operation_children`, and provide the only lifecycle/claim/occurrence batches. Native normalization owns copied artifacts, scope, supplemental descriptors, report contexts, and full nested occurrence records before opening authority.
- Exactly one query-only transaction enforces selected-spec pending and global child-ID guards, then fully captures/audits retained history before candidate rejection interpretation. Existing candidate and source-validation owners supply diagnostics. Native full issue occurrence payloads must associate proposed children, supplied after contexts, and exact retained provenance. A clean check alone reaches shared journal `planned_effects` and `_overlay`; rejected candidates have no history.
- Ordinary failures exit the public catch before constructing the bounded `IdentityStoreError`, with no cause/context. Process-control exceptions retain object identity.
- No changes to existing transformation owners, codecs, schemas, graph assembly, runtime, CLI, provider, state or publication writers. No installation, main-branch changes, smoke edits, subagents, independent reviewers, capacity runs or full-unit runs.
- Root's dirty `progress.md` and all plan/brief/report files are excluded from scoped commits.

## First RED/GREEN chronology

All test commands below ran from the worktree above. In the command table, `P` expands verbatim to `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`; `T` expands to `tests/unit/test_element_identity_candidate_preview.py`. These abbreviations only shorten this report; the actual invocations used the complete executable and file paths.

1. Before any production edits, created the prescribed native test with exact `FR-000001`, WASD/arrow-key rendered definitions, `Movement` subject, `reserve`/`create`/`revise` IDs, and existing checker/history comparisons.
2. Ran `P T::test_candidate_preview_uses_exact_journal_operations -q`. Native allocation, typed parsing, lifecycle creation, clean existing candidate check, and exact proposed revisions `1`/`2` assertions all succeeded. The only failure was at the missing public method:

   ```text
   E AttributeError: 'IdentityStore' object has no attribute 'preview_identity_candidate'
   tests/unit/test_element_identity_candidate_preview.py:39: AttributeError
   1 failed in 0.26s
   ```

3. Notified root of this actual missing-method RED before production code.
4. Added the complete narrow reader and method. Ran the identical command:

   ```text
   .                                                                        [100%]
   1 passed in 0.25s
   ```

5. Notified root of first GREEN. There were no subsequent production amendments. All later amendments before the covering run expanded/corrected the new tests or added storage documentation.

## Every actual test invocation and result

| Order | Actual command (with P/T expansions above) | Result |
| --- | --- | --- |
| 1 | `P T::test_candidate_preview_uses_exact_journal_operations -q` | Expected missing-method RED: 1 failed in 0.26s. |
| 2 | `P T::test_candidate_preview_uses_exact_journal_operations -q` | First GREEN: 1 passed in 0.25s, pristine. |
| 3 | `P T -q` | 9 failed, 13 passed in 2.35s. New native fixture mistakes described below; production unchanged. |
| 4 | `P T -k 'native_nested or proposed_claims' -q` | 5 failed, 6 passed, 11 deselected in 1.48s. U/A label correction succeeded; new U-reference span correction was itself off by one. |
| 5 | `P T -k proposed_claims -q` | 7 passed, 15 deselected in 0.98s, pristine after literal span restoration. |
| 6 | `P T -k 'issue or supplemental or absent or used_and_claimed or stale_lifecycle or full_retained' -q` | 1 failed, 29 passed, 23 deselected in 2.78s. Imported-only subject corruption did not violate the native audit; fixture corrected below. |
| 7 | `P T -k 'full_retained or real_writer or caller_records or result_owns or malformed_request or public_exception or import_orders' -q` | 1 failed, 33 passed, 51 deselected in 2.35s. All behavioral cases passed; operation-subclass fixture constructor rejected before public method invocation. |
| 8 | `P T -k 'operation-subclass or query_only_with or sealed_capture' -q` | 3 passed, 84 deselected in 0.82s, pristine. |
| 9 | Full nine-module command below | 590 passed in 33.83s, pristine. Executed once. |

The first broad new-module run output was truncated by the output budget, but its complete failure summary identified all nine failures and its result count is retained above. No failures were omitted or characterized as product REDs. All later focused failure outputs were available. Subprocess import-order tests invoke the same environment's `sys.executable -c` with `PYTHONPATH=src`; both return exit 0 with empty stdout/stderr. No standalone Python diagnostics were run.

### Fixture corrections, in actual order

1. The initial U/A clean-edit fixtures used `U-old` and `A-old`, which are valid ledger labels but are not declarations in the native discovery parser. Their declaration batches were empty, causing native `apply_lifecycle` fixture setup to reject an empty adoption batch. Changed them to historical supported `U-001` and `A-001`; retained `T-S01` coverage exercises legacy task labels. No parser/semantic changes.
2. The proposed claim fixture also used unparsed `U-old`, so its expected second reference observation was absent, source diagnostics prevented a passing history, and the invalid-target-revision expectation could not yet reach projected bindings. Changed it to imported/unassessed `U-001`. During that correction, mistakenly changed its literal anchor from `span:18:23` to `span:17:22`. The next focused result exposed only that new source-binding mismatch; restored the independently counted `18:23` span. All seven claim variants then passed, including valid source plus invalid target revision becoming `IdentityStoreError`.
3. The unrelated-spec authority-damage fixture changed only an imported entity's subject. That does not violate the existing audit's retained-history invariants. Replaced this test damage with a real adopted unrelated-spec revision followed by corrupted retained revision content, exercising its stored digest. Both same-spec and unrelated-spec corruption now raise bounded authority errors even with malformed candidate content. Existing authority semantics remain unchanged.
4. `PublicationOperation` rejects subclasses in its constructor. Changed the malformed boundary fixture to construct the adversarial subclass with `object.__new__` and copied slots, following the existing journal tests. This lets the public normalizer actually reject the already constructed malformed record before opening authority.

### Covering command and pristine output

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_candidate_preview.py tests/unit/test_definition_identity_candidate.py tests/unit/test_issue_identity_candidate.py tests/unit/test_element_identity_reference_sources.py tests/unit/test_element_identity_binding_preview.py tests/unit/test_element_identity_snapshot_preview.py tests/unit/test_element_identity_publication_history.py tests/unit/test_element_identity_candidate_sources.py tests/unit/test_spec_graph_captured.py -q
```

```text
........................................................................ [ 12%]
........................................................................ [ 24%]
........................................................................ [ 36%]
........................................................................ [ 48%]
........................................................................ [ 61%]
........................................................................ [ 73%]
........................................................................ [ 85%]
........................................................................ [ 97%]
..............                                                           [100%]
590 passed in 33.83s
```

Exit status 0. No warnings, skips, collection errors or stray output. The nine-module process was started once and its continuing output collected without rerunning it.

## Behavioral evidence and self-review

- 87 new cases cover complete SQL-state immutability; v3 prepare/apply retry and durable reopen equality to the complete preview; creation, revision, replacement, split, merge, retirement; six/seven-digit string labels; supported historical labels; native nested requirement and task edits; preserved U/A captions/subjects; supplemental projection/inventory descriptors; absent-versus-present-empty images.
- Independently specified exact sorted diagnostics cover removal, renumbering, out-of-scope edits and operation content differing from rendered candidates. Explicit claims verify after-image hashes and exact span/target/relation. Reference observations remain retained assessments: old FR evidence stays revision `1` and historical after proposal `2`, while imported U remains unassessed. Omitted claims do not synthesize stored claims.
- Issue tests cover orphan and missing child operations; changed reports with and without matching children; all seven occurrence fields; retained authenticated historical reports without a new operation; explicitly repeated retained occurrences under a fresh child; missing before provenance despite matching proposed child; malformed report hash despite exact proposed/context association. Existing body/report/display/revision owners still decide acceptance.
- Pending selected-spec previews fail even with empty operations. Another spec's independent pending intent does not block an unrelated empty preview. Used and permanently claimed children are rejected globally across ordinary/prepared/applied/released states. Stale lifecycle proposals remain candidate diagnostics. Corrupt retained revisions override candidate diagnostics with an authority exception.
- Transaction-entry mutation changes caller artifacts, outer sequences, scope, supplemental records, nested before/after occurrence slots and operation payloads, but cannot change the selected request. Result records are immutable and independently detached from candidate owner's returned diagnostics and references.
- Exact-type/subclass/deleted-slot/custom recursive/raising-sequence and encoding cases reject before authority. Ordinary errors have the exact bounded message and no cause/context; KeyboardInterrupt, SystemExit and GeneratorExit propagate as the original objects. Both import orders preserve native class identities.
- A wrapper around the real candidate helper coordinates a real second writer with events. The reader uses one real transaction with a SQL authorizer rejecting writes. The writer imports a new unrelated identity and reaches COMMIT while the reader is between candidate work and overlay, but cannot complete under rollback-journal locking until the reader exits. The result exactly equals the old snapshot. Once the writer commits, the still-valid lifecycle request with the stale complete history hash is rejected by real v3 preparation. No sleeps, stress loops, mocked store/snapshot outputs or production hooks.
- A separate read-path test counts exactly one history capture and one transaction, verifies `PRAGMA query_only=ON`, and attempts actual SQL writes in the existing planner wrapper, which SQLite rejects as readonly. Public nested readers and allocation/lifecycle/binding/publication/source/managed writers are blocked, as are source capture/manifest/projection entry points, canonical memory planner/miner, graph assembler and provider/runtime/memory imports. Only authority metadata/database reads and the existing identity helper path are allowed. Whole logical SQL state remains unchanged.
- Actual integration: native sealed source capture -> native candidate source assembler -> this reader -> native projected source images -> native canonical planner and explicit deterministic audit observation -> captured graph -> real v3 identity journal prepare/apply/reopen. Independently asserts `spec:demo`, `req:demo:FR-000001`, proposed revision `2`, exact old revision content, historical claim flag and its `ASSESSES_REVISION` edge. Complete graph rendering with post-application history equals retained projected graph bytes. Real source bytes remain original and no graph file exists.
- Self-reviewed staged production diff for transaction ownership, detach depth, occurrence identity, diagnostic-vs-authority distinction, helper reuse, import cycles, bounded exceptions and read-only boundaries. No source changes were needed after first GREEN. `IdentityStore` and storage documentation are already large existing files; additions remain the specified thin method and one section. No structural refactor.

## Tested tree and amendments

Before the covering run, staged only the four scoped files. `git diff --cached --check` passed. `git write-tree` returned:

```text
f52834738768946938a19b0b16def6c55c72db3a
```

This is the exact staged tree tested by the nine-module run. At that point the only tracked unstaged change was root-owned `.superpowers/sdd/2026-09-13-coherent-identity-candidate-preview/progress.md`. No implementation/test/doc amendments occurred after staging or after the covering run. This report is administrative, remains outside the scoped tree, and records later commit verification below. No unchanged postcommit test reruns.

Final command:

```sh
git diff --exit-code -- src/harness/element_identity_candidate_preview.py src/harness/element_identity_store.py tests/unit/test_element_identity_candidate_preview.py docs/element-identity-storage.md && git diff --cached --check && git write-tree && git commit -m "feat(identity): preview candidates and exact journal history coherently" && git rev-parse HEAD HEAD^{tree} && git status --short
```

Exit 0. No unstaged scoped changes; cached whitespace check clean. Commit `24186d390b2473531ea223f51d05d4cea7f460e0` has exactly the tested tree `f52834738768946938a19b0b16def6c55c72db3a`, four files and 939 insertions. Final tracked status shows only root's dirty progress file. The only later amendment is this administrative report update recording the commit; code, tests and storage documentation are unchanged. No postcommit tests were run.

## Read-only diagnostics and command ledger

All commands ran in the task worktree unless reading an absolute skill path. File reads were limited to the brief, required implementer prompt, applicable instructions, exact integration owners, existing native fixture tests and storage docs; no whole plan or unrelated ledger was read.

Actual Git/diagnostic commands, in chronological groups:

1. `pwd && sed -n '1,140p' .superpowers/sdd/2026-09-13-coherent-identity-candidate-preview/task-1-brief.md`: confirmed exact worktree and read all 85 brief lines, exit 0.
2. `rg --files -g AGENTS.md -g CLAUDE.md -g '*element_identity*' -g '*identity_candidate*' | head -70`: native file discovery, exit 0.
3. `git status --short` (combined with snapshot preview source/test reads): only root's dirty progress present initially, exit 0.
4. `rg -n 'preview_identity_history|check_identity_candidate|TYPE_CHECKING' src/harness/element_identity_store.py`: found existing thin reader/check patterns, exit 0.
5. `rg -n 'def (validated_operations|operation_children|planned_effects|check_identity)' src/harness/element_identity*`: found exact existing helper owners, exit 0.
6. `rg -n '^def test_|^def ' tests/unit/test_definition_identity_candidate.py tests/unit/test_spec_graph_captured.py tests/unit/test_element_identity_candidate_sources.py tests/unit/test_element_identity_reference_sources.py tests/unit/test_element_identity_snapshot_preview.py`: native fixture discovery, exit 0.
7. `rg -n 'LexiconProjectionSource|EvidenceInventoryContext' tests/unit/test_definition_identity_candidate.py tests/unit/test_discovery_identity_candidate.py tests/unit/test_element_identity_candidate_sources.py tests/unit/test_element_identity_bundle.py`: exit 2 because the last guessed test filename does not exist; no matches from the existing files. Corrected discovery in the next command, no changes.
8. `rg -n 'EvidenceInventoryContext|LexiconProjectionSource' tests/unit -g '*.py' | head -22`: found actual `test_supplemental_identity_bundle.py`, exit 0.
9. `rg -n 'def _transaction' src/harness/element_identity_store.py`: existing transaction at line 286, exit 0.
10. `rg -n '^def |^class ' src/echelon/spec_memory_miner.py src/harness/squad_publication.py src/harness/squad_source_snapshot.py src/harness/squad_source_manifest.py src/echelon/spec_graph_captured.py | head -60`: exact forbidden high-level owner targets, exit 0.
11. `rg -n 'def _validate_input' src/harness/element_artifacts.py && sed -n '95,135p' src/harness/element_artifacts.py && git diff --check && git diff --stat && wc -l src/harness/element_identity_candidate_preview.py tests/unit/test_element_identity_candidate_preview.py`: confirmed native UTF-8 validation; diff-check clean; module/test lengths 87/762; exit 0.
12. `git diff --check && git diff -- src/harness/element_identity_store.py docs/element-identity-storage.md && git status --short`: clean scoped source/doc patch plus root progress and two new files; exit 0.
13. `git branch --show-current && git rev-parse HEAD && git add src/harness/element_identity_candidate_preview.py src/harness/element_identity_store.py tests/unit/test_element_identity_candidate_preview.py docs/element-identity-storage.md && git diff --cached --check && git write-tree && git diff --cached --stat`: correct branch/BASE, exact tree above, four files/939 inserted lines, clean diff, exit 0. Staging was the requested scoped implementation action.
14. `git diff --cached -- src/harness/element_identity_candidate_preview.py src/harness/element_identity_store.py && git diff --name-only && git diff --cached --numstat`: self-review production patch, root progress the only tracked unstaged file, scoped counts 67/87/23/762, exit 0.

Additional source inspection used `cat`, `sed -n`, `head`, and `tail` on the paths identified above: all returned exit 0. Read the full implementer prompt, repository AGENTS/CLAUDE instructions, test-driven-development and verification-before-completion skills, writing-good-tests reference, and systematic-debugging skill when diagnosing fixture failures. Targeted source reads covered candidate normalization/checking, issue normalization/preparation, bindings, bundle normalization, publication validation/planning, snapshot capture/overlay, store transaction, reference source matching and the existing native fixtures named above. Some combined discovery outputs were truncated; subsequent targeted reads supplied the specific native contracts used. No filesystem mutation diagnostic or external service was invoked.

## Remaining authority boundaries

This is a structural read-only observation, not semantic verification, source freshness, accepted-source ownership, dependency completeness, a lease, receipt or publication permission. The integration test's deterministic audit is an explicit observation, not proof of semantic review; opaque manifest/recovery fixture claims do not publish files. No graph is sealed/published. Historical evidence is retained, not relabeled as proof of new content. Rejected candidates cannot update canonical artifacts, graphs or memory, and identity failures cannot become quality debt or banzai waivers. Agents propose content and edits; they do not allocate IDs, mutate the ledger or certify publication. Managed controller ownership, source byte/dependency capture and guards, semantic review, producers/runtime/manual/CLI enforcement, graph sealing, joint durable publication/recovery, bounded repair and final offline regression remain outside this inactive integration task.
