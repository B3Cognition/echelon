# SDD ledger — plan: docs/superpowers/plans/2026-09-13-captured-artifact-memory-audits.md

## Scope and recovery

Approved durable-ID integration, offline only in delivery-controller-contract. Parent checkpoint 4981dc13; prior captured canonical audit is complete and must not be redispatched. This plan has one cohesive task. No main/global install/stopped-smoke mutation or live activation. Retain this workspace until whole-branch review and exhaustive final rulings.

## Preflight

Spec: docs/superpowers/specs/2026-09-12-durable-element-identities-design.md (approved, read completely in this execution).

| Tasks/interfaces checked | Producer versus consumer | Finding |
| --- | --- | --- |
| Task 1 self-consistency | Two public adapters, scoped private extractions and one new test module versus exact seven-module cover | All modified/new owners named; existing tests remain unchanged; no public runtime activation. |
| Task 1 canonical acquisition | Existing detached complete read/cohort helper versus canonical and artifact carriers | Preserve canonical parsing; explicitly convert existing carriers at boundary; no new scan policy. |
| Task 1 artifact classifiers | Native classification and bounded extras versus captured complete extras | Share classification, preserve native warning/status/count rules; only new acquisition gets strict completeness. |
| Task 1 evidence source/frontmatter | Captured logical bytes versus native lifecycle and metadata | Exact original hashes, universal newline parsing only, default landed gate before acquisition; unrelated target loading not claimed. |
| Task 1 RE catalogs | Pure descriptor validation versus native kind/room selection | Explicit legacy/catalog modes, all descriptors validated before filtering; index presence is not association proof. |
| Task 1 report conversion | Generic normal reports versus existing domain report constructors | Share normal conversion; new failures use valid domain fields; legacy exceptional behavior remains unchanged. |
| Task 1 graph consumer | Actual returned reports versus existing captured contributions | Tests only, retain returned origin and native statuses; no fabricated completeness/current-revision/publication authority. |

Ruling: 36 — Extend captured observation to evidence and RE with the native default landed gate and explicit allow_unlanded opt-in; select RE legacy mode only when no index witness exists, and catalog mode only with a nonempty fully validated supplied descriptor tuple, captured regular index witness and eligible selected artifact. Preserve native ordering, metadata and classification. Index presence is not catalog association proof; new operational failures return valid domain reports while legacy exceptional paths remain unchanged. — Captured bytes alone cannot establish lifecycle or registry authority, and missing/damaged catalog input must not silently downgrade to legacy selection. — If wrong, revise the inactive source/catalog/landed contract and parity tests or add an explicit captured-registry association; no IDs, revisions, graph keys, native legacy wire, journal receipts, canonical sources or live deployment need rewriting.

Task 1: dispatched to /root/captured_artifact_memory_audits (Astra/high), BASE e1abcd63fff0300373b919fd3ab00a35785136f1. Ruling 36 is selected, not yet implemented or reviewed. Root-only ledger is excluded from worker commits.

Task 1: root received native-grounded first RED: exact required single test, 1 failed in 0.61s at absent new module only after matching old rows passed native audit and candidate rows against old disk failed. No fixture correction and no production edits before RED.

Task 1: root received first GREEN: exact required single test, 1 passed in 0.61s. Worker reports scoped production implementation complete and is building parity/selection/cohort coverage; no additional owner or architecture escalation.

Task 1: worker reports new module 174 cases passed; expanded run 251 passed / 6 failed on test-only read-count expectations at exact budget. Native scanner correctly performs an overflow probe on each full pass; corrected fixture and scoped six cases passed in 0.62s. Full exact commands/timings will be read from report before review.

Task 1: root received covering-run notification: exact seven modules, 821 passed in 4.12s, exit 0. Staged tested tree 9cde9127a5b60f2954ae8bff19c4bccc31b9aee3, eight scoped paths only; root progress/future plan excluded. Worker preparing commit/report, no production/test amendments after cover.

Task 1: implementation 0768a2acc54a1b010b04624815bc8c1b29f0a868, report-only 41c6fcdb9c9e34d6098dec0958011912eace2eb2. Root read all 95 report lines and verified implementation tree equals reported tested tree and final commit changes only report. Complete tests include 94 passed in 1.35s; 174 in 1.92s; 6 failed/251 passed in 2.34s (fixture probe count); six scoped in 0.62s; 268 new-module cases in 2.31s; once seven-module 821 in 4.12s, pristine. No post-cover implementation changes.

Task 1: original-BASE full 97673-byte package review-e1abcd63..41c6fcdb.diff dispatched to fresh /root/review_captured_artifact_memory_audits (Astra/high). Awaiting spec and quality verdicts. No unchanged tests rerun by root.

Task 1: independent review spec compliant and quality Approved, no Critical/Important/Minor. Reviewer read full package/report, recovered cut-off classifier/extras bodies, and named focused parser/source-manifest/descriptor delegation checks. Native generic parser remains unchanged; strict captured exact-type parsing follows the complete-observation contract. No tests rerun or checkout changes.

Task 1: Cannot Verify resolution — temporal RED/GREEN execution supported by root's contemporaneous worker notifications and full exact report, with independently verified implementation tree and report-only final commit. Physical/catalog/configuration/revision/publication authority are explicit inactive-boundary nonclaims, not missing claims of this task. No unresolved cross-task finding.

Task 1: complete (commits e1abcd63..41c6fcdb, review clean). Ruling 36 implemented and independently reviewed. Administrative checkpoint only after tested implementation; no retest claim for administrative tree. Retain workspace until final whole-branch review/rulings. Continue automatically to the prepared managed-retarget-rewind-exclusion plan.

## Root read-only integration reconnaissance (not implemented or selected protocol)

- `spec_graph.build_spec_graph(root, selector)` has explicit root but legacy disk acquisition; `write_spec_graph(graph, spec_dir)` and audit writer have no explicit root, sharing `_write_spec_graph_bytes`. Guarding build alone is not complete writer coverage. `audit_spec_graph` converts build failures to source-unavailable; direct audit-write CLI can still publish that report. No graph gate currently exists in Squad.
- `workspace_graph_refresh.refresh_workspace_graph(write=True)` refreshes RE memory first, then requirement/evidence memory and spec graphs, then workspace graph/audit. A guard placed only at spec graph writing would be too late for prior memory effects. Write=False is read-only composition.
- Retarget has three distinct locked mutation owners in `spec_retarget.py`: `_apply_retarget`, `_resume_existing_retarget`, `_adopt_prepared_retarget`; all take spec mutation, Phase A and baseline-run leases. New operation's first durable effect is append_prepared_revision; resume/adoption callback and invalidation/bootstrap paths differ. Guarding Squad alone does not cover these.
- Retarget recovery is separately invoked by `src/echelon/cli.py` rewind flows, including `resume_committed_retarget_recovery` and `recover_retarget_checkpoint`; plain checkpoint restoration also occurs in proportional_quality. These need scoped owner analysis before claiming all legacy writes excluded.
- Existing `IdentityStore.managed_identity(spec_id=...)` provides a query-only spec lookup without inventing a run ID, but authenticates some retained associations rather than being a new mutation lease. Existing execution guard requires actual physical/declared run IDs and rejects damaged authority parents. No graph/retarget guard contract or new store API selected by this reconnaissance.
- A few discovery searches named nonexistent guessed module paths; corrected using rg results. These are read-only discovery misses, not test failures.
- `_require_recovery_revision` can itself advance retarget history while reconciling captured receipts; any future admission must precede that branch, not merely its caller's later restore try. `_cmd_rewind` consumes native prepare_rewind same-head applied=True even for nominal preview, so its entire entry needs admission; the standalone lower-level preview has no effects itself. A future root plan was drafted but is untracked/unexecuted and excluded from this worker's commits.
