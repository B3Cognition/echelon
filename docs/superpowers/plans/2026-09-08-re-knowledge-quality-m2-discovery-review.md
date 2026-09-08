# RE M2 Discovery Review Admission Implementation Plan

> **For agentic workers:** Use test-driven development for the admission boundary and independent code review before handoff.

**Goal:** Prepare an independent review context for a staged discovery proposal and admit a complete, evidence-grounded ownership/domain review without confusing it with execution certification or completed analysis.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, sections 5–7 and M2.

**Architecture:** Extend the existing passive discovery boundary with authenticated, read-only proposal replay. Add one passive review boundary using the same screened evidence and object store. It invokes no provider, adds no scheduler or resource account, and cannot activate an analysis plan. Future review dispatch must use the existing logical-run account and prove an independent invocation. The review receipt is needed to bind the exact screened review to the exact candidate/context and retain actionable findings across restart.

**Tech stack:** Existing Python canonical objects, pinned snapshot reader, secret screening, pytest synthetic Git fixtures and neutral Prosaic/runtime contracts.

## Constraints and sequencing

- Remain in the user-selected checkout/branch. No install, paid provider call, source-repository/stash changes, default/budget changes or generated `runs/` commits.
- Production adapter integration remains gated: the current shared backends print unscreened output (`openai_compatible.py:run_prompt` and Codex progress), and the CLI path does not yet prove tools-free execution and complete reservation enforcement. Do not weaken those requirements or change provider selection to bypass them.
- This step supplies review **admission**, not certified semantic review. Every resulting receipt explicitly requires independent execution certification before plan activation. No debt acceptance, category applicability decisions, analysis completion or publication is introduced.
- Existing schema-1 passive and schema-2 captured discovery receipt identities remain unchanged.

## Task 1 — Authenticated proposal and review admission

Files: `src/harness/re_v2/knowledge_discovery.py`, new `src/harness/re_v2/knowledge_discovery_review.py`, new `tests/unit/test_re_v2_knowledge_discovery_review.py`. A narrow pure-validation extraction in `knowledge_evidence.py` is permitted to reuse the exact existing screening rules during read-only replay; ordinary admission retains quarantine behavior and screening policy identities remain unchanged.

Interfaces:

```python
DiscoveryBoundary.read_proposal(binding_id: str, receipt_id: str) -> dict
DiscoveryReviewBoundary(discovery: DiscoveryBoundary)
DiscoveryReviewBoundary.provider_bytes(binding_id: str, proposal_receipt_id: str) -> bytes
DiscoveryReviewBoundary.admit(binding_id: str, proposal_receipt_id: str, output: bytes) -> str
DiscoveryReviewBoundary.read_review(binding_id: str, proposal_receipt_id: str, review_receipt_id: str) -> dict
```

- [x] RED/GREEN: `read_proposal` reconstructs and validates the exact receipt, normalized proposal and optional raw capture against authenticated pinned evidence. Reject forged/mismatched receipts, changed evidence or missing objects. Reads must not repair/recreate objects or write new admission receipts. Re-screen replayed authorial bytes with the same rules using a pure validator, so self-consistent forged hashes cannot export unsafe text. Refactor validation/persistence separation only as needed; preserve all existing identities.
- [x] RED/GREEN: reviewer context contains only the normalized candidate and authenticated safe discovery context, its candidate ID, plus deterministic review obligations. No private snapshot/mapping paths, producer transcript/reasoning, or previous verdicts. Bound canonical context at the existing 262,144-byte ceiling; oversized context fails closed without truncation.
- [x] RED/GREEN: screen the complete reviewer output before parsing, diagnostics or ordinary persistence; reject duplicate/unknown fields, invalid shapes and foreign evidence. Closed errors; local storage/authority faults are not model rejection. Unsafe results use the existing restricted quarantine.

Reviewer output schema (all top-level fields mandatory, no extras):

```json
{"schema_version":1,"kind":"discovery_review","proposal_id":"sha256:...","verdict":"ready","domains":[],"subjects":[],"inventory":[],"overlaps":[],"findings":[]}
```

`domains` and `subjects` each cover every candidate key exactly once with `{key, verdict, rationale, evidence_ids}`. Verdict is `supported` or `revise`. A supported row needs nonempty visible supplied evidence, including at least one of that candidate's evidence IDs. Revision feedback may cite supplied withheld evidence or no evidence to identify absence. All rationales use the existing bounded nonempty text validator.

`inventory` covers every inventory path exactly once with `{path, owner, disposition, rationale, evidence_ids}`. The owner must equal the candidate owner, including null; the reviewer cannot edit the candidate. Dispositions:

- `owned`: nonnull owner, visible evidence for that same path, and at least one same-path cited projection from the owner's proposed evidence. This verifies structural grounding, not semantic truth.
- `non-behavioral`: null owner, cited fully visible whole-file evidence for that exact path. It remains the independent reviewer's semantic judgment; partial/redacted evidence cannot prove absence.
- `excluded`: null owner, deterministic evidence that the inventory item is empty, nonregular/opaque, or a policy-excluded path. Explicit disposition, no invented domain. Do not treat a partially redacted ordinary source as entirely excluded.
- `unknown` or `needs-assignment`: null or candidate owner, supplied references if any; always requires revision. Unassigned required work cannot become accepted debt.

`overlaps` covers exactly every unordered pair of subjects whose proposed evidence touches at least one common inventory path, even if the byte ranges differ. Context explicitly enumerates `overlap_pairs`. Compute no more than 4,097 pairs: reject more than 4,096 before returning provider bytes with `discovery-review-overlap-bound`; hierarchical review is outside this increment. Each response row is `{subject_keys:[a,b], disposition, rationale, evidence_ids}`. Accept either order and normalize the pair; reject duplicates, missing and extraneous pairs using the same calculation. `shared-evidence` and `distinct` require visible supplied references to a common path from each participant's proposed evidence; `conflict` requires revision. Supporting overlap is not duplicate primary ownership.

`findings` are bounded `{target, reason_class, rationale, evidence_ids}` records. Target is `source` or a proposed domain key; reason class is `missing-behavior`, `unsupported-domain`, `ownership`, `overlap`, or `evidence-gap`. Preserve findings as screened feedback with stable normalized IDs. Require at least one finding for `verdict: revise`; reject `ready` with findings, revised domain/subject, unresolved inventory or overlap conflict. Keep all proposal questions and all category obligations unchanged in the context; no category-completeness assertion.

- [x] RED/GREEN: a valid receipt binds proposal receipt, normalized review, exact screened response, reviewer context hash and outcome (`ready_for_planning` or `revision_required`), with `execution_certification_required: true` and `analysis_certified: false`. `read_review` reconstructs it read-only; an arbitrary hashed JSON object is not authority. Reopening retains findings and neither grants execution certification nor overwrites candidate ownership.
- [x] Tests use real temporary Git snapshots. Include later-range overlap, missing/duplicate inventory, forced false-ready, withheld-only evidence, partial/redacted absence assertions, config-only/no-domain proposal, stable normalized row identities, exact capture mismatch, corrupt stores, canaries and no writes on replay. Existing discovery/acquisition/dispatch tests must remain green.

## Task 2 — Neutral review contract and verification

Files: new `prosaic/subagents/echelon.re-discovery-reviewer.md`, new `runtime/workflow/phases/re-knowledge-discovery-review.md`, `runtime/workflow/definition.yaml`, role inventory docs/tests and spec status.

- [x] Add a tools-free neutral reviewer role with paired ALWAYS/NEVER rules: examine evidence independently, challenge directory-derived domains and missing behavior, reconcile all inventory/overlaps, preserve unknowns, never edit candidate/state or declare analysis complete.
- [x] Runtime phase owns exact inputs/output/routing and requires fresh independent invocation, same aggregate account, screening and bounded capture. Reference the role as a disabled internal contract; installed routing stays unchanged.
- [x] Run focused regression and workflow/packaging checks; obtain independent read-only review, resolve findings, update exact evidence and remaining M2/M3/M4 prerequisites. Leave this new increment uncommitted for handoff unless the user asks otherwise.

## Progress

Both tasks complete. Independent review identified three replay/bounding defects; all three fixes passed scoped independent re-review. Fresh full compatibility verification: **853 passed in 197.25s**. The preceding dispatch increment is committed at `d5507d33`; this passive-review increment remains uncommitted for handoff.

Wiring/packaging verification: **268 passed in 39.28s**. Added a separate controller-to-review handoff regression in `tests/unit/test_re_v2_knowledge_review_handoff.py`; RED confirmed the missing review module after a real scripted discovery dispatch. It checks preserved charges, no extra provider call and no activation/certification from passive review.

Intermediate compatibility after read-only proposal replay: existing discovery dispatch/acquisition selection **85 passed in 48.62s**. Final combined verification remains pending.

Task 1 RED/GREEN: missing proposal replay failed three tests; missing review module failed its new tests; self-consistent forged unsafe proposal/review objects failed two replay regressions before pure screening was added; malformed container values failed two error-taxonomy checks before classification was corrected. Implementer final evidence/knowledge selection: **191 passed in 92.15s**. Parent review/handoff confirmation: **34 passed in 15.16s**. Full compatibility and independent review are running against the frozen implementation.

Full parent compatibility run: **850 passed in 196.78s**. Selection is the preceding dispatch plan's 816-case verification command plus `tests/unit/test_re_v2_knowledge_discovery_review.py` and `tests/unit/test_re_v2_knowledge_review_handoff.py`. `git diff --check` passed. Independent review remains the final gate for this increment.

Review fixes required: screen replayed authorial bytes, not generated receipt hash mappings (valid `api-token` subject keys must replay); enumerate and preflight bounded unordered overlaps; bound normalized review and receipt bytes before any ordinary persistence, not only raw response bytes. Preserve forged-canary rejection, exact receipt reconstruction and read-only replay. These findings require focused RED/GREEN regressions and scoped independent re-review before handoff.

Review fixes completed: five focused RED cases reproduced the defects, then all passed. Evidence/discovery/acquisition/dispatch/review/handoff verification: **194 passed in 96.91s**. Scoped independent re-review approved all three fixes with no remaining finding. Pure authorial screening and exact receipt reconstruction remain intact; generated hash mappings are no longer mistaken for source secrets. Context enumerates bounded canonical overlap pairs while authorial responses accept either order. Normalized review and receipt size checks precede every ordinary write.

Final parent verification after those fixes: **853 passed in 197.25s**, using the same full compatibility selection above. `git diff --check` passed. No installation, live provider call, source-workspace change, stash operation, budget increase or generated `runs/` staging occurred. Remaining M2 work includes actual independent reviewer dispatch/certification in the same account, production provider isolation and pre-log screening, semantic reconciliation and analysis revisions/invalidation. M3 publication/refresh/consumer integration and separately authorized M4 live trials remain pending; this is not a release-ready RE workflow.
