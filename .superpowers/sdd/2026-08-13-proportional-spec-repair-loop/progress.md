# SDD ledger — plan: docs/superpowers/plans/2026-08-13-proportional-spec-repair-loop.md

Spec: docs/superpowers/specs/2026-08-13-proportional-spec-repair-loop-design.md
Merge base at start: df41399fb4981e7d3660a416a07a8e4d404d93e2
Implementation base at start: 057b0a7d408c11ca63640c8a52b04bea80677af4
Workspace: linked worktree `feat/simplified-run-summary`

## Preflight consistency scan

| Scope | Producer / consumer relationship | Finding |
|---|---|---|
| Task 1 internal | Projection and shared detector feed metric-specific analysis and compatibility parsing | Consistent. The implementation may add a category-input seam inside the metric engine because one aggregate string cannot satisfy the specified field separation; thresholds and public compatibility output remain unchanged. |
| Task 2 internal | Initialization, validation, accounting, state schema, and controller ownership | Consistent. Generic state initialization may not yet know authoring mode, so run-local lazy initialization at the first proportional controller boundary satisfies the spec when eager initialization is impossible. |
| Task 3 internal | Candidate manifest feeds ranking and narrow digest-verified restoration | Consistent. A dedicated Phase A candidate checkpoint created at the assessment boundary is an existing Phase A checkpoint for subsequent ranking/restoration. |
| Task 4 internal | Static sealed policies plus controller-only dynamic recommendation feed v2 decisions | Consistent; provider-authored options stay forbidden. |
| Task 5 internal | WHAT accounting and WHY2 assessment feed routing and decision resolution | Consistent. Automatic no-op and authorized-extension no-op intentionally have different consumption semantics. |
| Task 6 internal | Debt artifact feeds digest-bound authorization and downstream prerequisite | Consistent; passing certificate remains separate and unchanged. |
| Task 7 internal | Verified debt state feeds publication, downstream context, status, and one terminal banner | Consistent; provider-limit and debt output remain independent. |
| Task 8 internal | Runtime workflow metadata and human docs describe controller-owned behavior | Consistent; YAML does not duplicate counters. |
| Task 9 internal | Retained fixture, full verification, live run, and final review validate prior tasks | Consistent; live provider unavailability must be reported, never converted to a passing claim. |
| Tasks 1 → 9 | `RequirementProjection` and role evidence are exercised by retained Hello World regression | Consistent. |
| Tasks 2 → 3 | `proportional_quality.py` state feeds candidate IDs and manifests | Consistent; Task 3 extends rather than replaces Task 2 APIs. |
| Tasks 2 → 6 | Controller-owned namespace later adds debt authorization | Consistent; both keys reject agent writes. |
| Tasks 3 → 5 | Candidate capture/ranking/restoration APIs feed WHY2 controller routing | Consistent. |
| Tasks 4 → 5 | Registered policies and handler name feed controller resolution dispatch | Consistent. |
| Tasks 4 → 8 | Phase graph policy contracts feed deployed workflow tests | Consistent. |
| Tasks 5 → 6 | `squad.py` routing creates the sealed decision consumed by authorization | Consistent; Task 6 extends the resolution effect without fabricating PASS. |
| Tasks 5 → 7 | Controller state feeds CLI recovery and terminal presentation | Consistent. |
| Tasks 5 → 9 | Controller integration tests receive final retained live-run regression coverage | Consistent. |
| Tasks 6 → 7 | Verified authorization and artifact feed publication/readiness/downstream prompts | Consistent. |
| Tasks 7 → 9 | Summary/status behavior is part of live acceptance evidence | Consistent. |
| Tasks 8 → 9 | Deployed runtime contracts are included in final package checks | Consistent. |

Ruling: Metric-family field separation may introduce a small internal category-input adapter rather than forcing every category through `analyze_text(text)` — the spec requires different evidence per family and unchanged thresholds/public compatibility — cost if wrong: a larger Understanding refactor than necessary.

Ruling: Initialize `phase1_quality_repair` lazily at the first proportional run boundary if `SquadState.initialize()` lacks the persisted authoring decision — the record must exist only for proportional runs — cost if wrong: callers expecting the key immediately after generic state construction would need adjustment.

Ruling: Use a dedicated uniquely named Phase A checkpoint at each completed WHY2 candidate boundary — it provides an immutable commit containing coherent candidate-owned artifacts before routing — cost if wrong: extra local checkpoint commits and ledger entries.

## Baseline

The 2026-08-13 pre-push baseline on this worktree recorded 1,627 passing and four failing tests before implementation: `test-codegraph-pinned-runtime.sh`, `test-run-analysis-polyrepo.sh`, `test-e2e-concurrent-run.sh`, and `test-e2e-orchestrator-prefixed-output.sh`. These failures are not classified as unrelated until reproduced or otherwise diagnosed during final verification.

## Task progress

Task 1: fix round 1/5 (4 addressed, 4 open — conventional ID compatibility, aggregate shared roles, testability cardinality, mixed FR/AC routing, conservative prose retention, meaningful action detection; commits d144fe8a..ecbca64a)

Task 1: fix round 2/5 (4 addressed, 3 open — direct depth false positives, fixed action vocabulary, heading overreach; commits ecbca64a..00a7ea33)

Task 1: fix round 3/5 (3 addressed, 1 open — auxiliary post-modal actions; commits 00a7ea33..489139f5)

Task 1: fix round 4/5 (1 addressed, 0 open — auxiliary post-modal actions; commits 489139f5..bdfecc02)

Task 1: complete (commits 057b0a7d..bdfecc02, review clean; independent verification 56 passed)

Task 2: fix round 1/5 (2 addressed, 0 open — exact numeric schema types and trustworthy legacy WHY2 migration; commits df711e4a..41c149fa)

Task 2: complete (commits bdfecc02..41c149fa, review clean; independent verification 671 passed)

Task 3: minor (deferred): checkpoint identity verification does not check the generated `Echelon-Origin: phase-a` and `Echelon-Action: checkpoint` trailers.

Task 3: minor (deferred): frozen candidate manifests contain mutable finding-route dictionaries inside the tuple field.

Task 3: fix round 1/5 (4 addressed, 0 open — immutable assessment binding, candidate sequence, committed-blob coherence, restoration evidence root/spec binding; commits e57ee02e..e4279da4)

Task 3: complete (commits 41c149fa..e4279da4, review clean with 2 deferred minors; independent verification 369 passed)

Task 4: minor (deferred): add a negative regression proving extension-exhausted preparation is rejected before the authorized extension is consumed.

Task 4: fix round 1/5 (1 addressed, 0 open — stable inclusive borderline comparison; commits 40bcb9ef..944ba3ae)

Task 4: complete (commits e4279da4..944ba3ae, review clean with 1 deferred minor; independent verification 337 passed)

Ruling: Task 5 may create the minimal public `phase1_quality_debt` builder/acceptance seam assigned to Task 6 because Task 5 explicitly requires `continue_with_debt` to invoke it; Task 6 still owns exhaustive authorization verification, invalidation, and downstream prerequisite behavior — cost if wrong: Task 5's diff/review surface is larger and Task 6 becomes a create-or-complete task rather than a pure create task.

Task 5: fix round 1/5 (5 addressed, 1 open plus 2 new — recoverable candidate/restore and debt effects, atomic no-progress sealing, authoritative CRITICAL blockers, global iteration, public run-loop tests; pending resolution and routed checkpoint findings remained; commits 7c50cd18..cbecdd77)

Task 5: fix round 2/5 (2 addressed, 0 open — pending restore resolution guard and dual route-bound checkpoint semantics; commits cbecdd77..212005f0)

Task 5: complete (commits 944ba3ae..212005f0, review clean; independent verification 601 public-path and 658 regression tests passed)

Task 6: fix round 1/5 (3 addressed, 2 new — lexical symlink safety, exact decision/completion/state binding, and safely sealed stale-debt replacement; exact exchange and retry directory durability remained; commits 3942cfe5..a34c5627)

Task 6: fix round 2/5 (2 addressed, 0 open — pinned final-preimage exchange and retry directory durability; commits a34c5627..b4179925)

Task 6: complete (commits 212005f0..b4179925, review clean; independent verification 483 currentness/controller and 935 Task 5/outbox regression tests passed)

Task 7: fix round 1/5 (5 addressed, 3 open — fail-closed pinned dispatch, publication recovery authentication, truthful narrative anchors, complete decision evidence, and specialist context; opaque placeholder ordering, contradiction semantics, and baseline growth remained; commits ea9d157d..ff1e780a)

Task 7: fix round 2/5 (3 addressed, 2 open — opaque executor context and baseline growth fixed; narrative contradiction and dedup semantics remained; commits ff1e780a..2e7f539d)

Task 7: fix round 3/5 (2 partially addressed, 2 open — clause-local filtering and normalized dedup improved but still over/under-classified action narration; commits 2e7f539d..fdfad0df)

Task 7: fix round 4/5 (2 partially addressed, 2 open — structural action/verdict splitting improved but missed pronoun/implied verdicts and broader work verbs; commits fdfad0df..1d692221)

Task 7: fix round 5/5 (2 addressed, 0 Critical/Important open — generalized conjunction verdict splitting and anchored completed-work classification; commits 1d692221..ceab4ff5)

Task 7: minor (deferred): provider-status lines beginning with completed-participle forms such as `Blocked`, `Limited`, or `Exhausted` can duplicate the authoritative provider-limit line; bounds and truth are preserved.

Task 7: complete (commits b4179925..ceab4ff5, review PASS with 1 deferred minor; independent verification 925 focused/adjacent and 420 full controller tests passed)

Task 8: fix round 1/5 (5 addressed, 0 open — automatic versus extension accounting, banzai recovery wording, hard-blocker catch-all, bounded status wording, and deployed-contract assertions; commits 69903eae..a0fdd5de)

Task 8: complete (commits ceab4ff5..a0fdd5de, review clean; independent verification 146 deployment/graph tests and 9 bundle checks passed)

Task 9: fix round 1/5 (1 addressed, 0 open — retained trailing `verifying FR-*` traceability metadata is excluded from normative scoring while references and ordinary normative uses remain; commits d759e244..a4beef3f)

Task 9: downstream finding (deferred): terminal `phase3-tasks-lexicon` exhaustion recommends `phase1-lexicon-derive`, targeting the wrong Lexicon phase.

Task 9: downstream finding (deferred): terminal summary claimed a published workspace specification although no workspace `specs/` directory existed; artifacts remained run-local.

Task 9: live finding (preserved): first changed proportional repair grew the retained Hello World candidate from 17 to 28 formal statements (+11) before passing certification; bounded accounting is correct but the growth remains material proportionality evidence.

Task 9: complete pending whole-branch review (commits a0fdd5de..a4beef3f, scoped review clean; independent focused verification 1448 passed; live Codex certification after 1 consumed changed repair and 1 unchanged unconsumed WHAT; downstream CLI later blocked separately)

Final whole-branch review: fix wave 1/1 committed as a83ffbfb. Addressed older-best debt currentness, legacy migration, legacy schema-v1 outbox recovery, repair-bound recommendation evidence, banzai COMMANDER E2E, and CLI SAGE type. Verification: 1688 affected/feature tests, run-all 1649/0, deployment 146, bundles 9/9, full pytest 8798 passing plus the exact 3 base-reproduced failures.

Final whole-branch review: STOP — 3 Important findings remain after the single authorized final fix wave: restore postimage verification can follow a raced symlink and a hard-kill exchange orphan can be staged; selected manifest SHA can be read from a different manifest than the one ranked; qualitative-only SAGE FAIL can bypass exact coverage and seal non-executable choices. Branch is not merge-ready without authorization for another fix wave.

Second final fix wave (user authorized): committed 4dfa11f4. Focused/adjacent and repository verification passed (feature 1474, run-all 1649/0, deployment 146, bundles 9/9, full pytest 8808 plus the same 3 base-reproduced failures).

Second final review: STOP — 3 Important findings remain. Restore does not preserve selected Git modes, is not checkpoint-verified after the final descriptor race window, and does not bind initial entry identity through reconciliation; combined candidate+restore validates the older selected manifest only after current-candidate Git/run-artifact mutation and candidate-list slots omit expected-ID binding; ordinary certification can ignore an authoritative SAGE FAIL/CRITICAL issues artifact when numeric/provider envelopes say PASS. Repeated restore fixes now require an architectural decision rather than another incremental patch.

Task 9: initial regression/live evidence committed at d759e244; review found one Important retained-projection acceptance gap.

Task 9: fix round 1/5 (1 Important addressed — standalone trailing `verifying <requirement IDs>` traceability is excluded from normative scoring while references remain; exact retained AC behavior, compatibility negatives, clean unchanged-threshold scores, provenance, and live-evidence boundaries recorded; commit a4beef3f)

Task 9 downstream defect (deferred): a terminal `phase3-tasks-lexicon` block recommends the Phase 1 spec-Lexicon repair command `echelon phase run phase1-lexicon-derive`.

Task 9 downstream defect (deferred): the terminal summary claims `Published specification at specs/001-do-hello-world-in` although the blocked live workspace has no published `specs/` directory and only run-local artifacts.

Task 5 (git-first recovery verification): focused recovery matrix 1137 passed; expanded feature suite 1727 passed; deployment 146 passed and bundle dry-run 9/9. Repaired a Task-4-scope perfectionist/schema-v1 compatibility regression exposed by the matrix (legacy fixtures had defaulted to proportional); 13 targeted tests passed. `run-all` had 1648 passed/1 failed and full pytest had 8882 passed/9 skipped/1 deselected/4 failed: the three reproduced capability-policy baseline failures plus one out-of-scope legacy journal fixture default-mode regression. Tasks Lexicon defects remain deferred unchanged.
