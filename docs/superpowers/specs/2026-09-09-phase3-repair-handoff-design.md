# Phase 3 repair handoff and independent issue closure

Status: approved approach; written design for implementation review.

## Goal and scope

Make existing Phase 3 spec-authoring repairs consume current findings, retire independently validated selections, and route technical investigation to the existing owner without granting new product-decision authority. Prove this on preserved spec008 after deterministic regression tests.

No new agents, no SOAR, no demo edits, no quality waivers, no budget increases, no super-banzai, no changes to delivery verification. WHY2/proportional decision semantics and semi-mode decision approvals remain unchanged. Shared context/state corrections must retain their existing callers' behavior.

## Evidence motivating the change

Workspace: `/Users/michalbachorik/work/browser-3d-game-stack-smoke`, run `spec-20260908-174947-206143`, spec `008-model-player-character-with`.

- Telemetry records 11 HOW invocations and 10 consensus cycles (30 staged dispatch records, not 30 independent consensus cycles).
- The final HOW context report, `context-budget/dispatch-0011-phase3-how-echelon.architect.json`, includes no issues/tasks/contracts and records zero matching journal entries. The provider subsequently read these artifacts, but remained constrained to the previous selected enum repair.
- `_coordinate_selected_issue_repair_updates` retires a Phase 3 selection only when the entire WHY3 verdict passes. A repaired enum therefore remains selected while unrelated geometry issues fail.
- `_render_issue_resolution_context` continues to render a `repaired` selection and directs the worker to address only that named issue.
- The journal selector repeats `phase`; `parse_context_pack_item` overwrites its first value. Even the intended selector excludes later consensus challenges.
- Final PLAN2 returns BLOCKED with an explicit ARCHITECT/SENTINEL handoff. Both remaining issues say agent repair, but `Banzai eligible: no`; candidate filtering yields no eligible decision and the run stops as `agent_blocked`.
- No evidence of token exhaustion: persisted usage 40,000,542 versus configured budget 999,999,000. Successful dispatch and structural validation did not establish issue resolution.

## Selected approach

Extend existing issue ledger, prepared-result validation, controller transactions, context assembly, owner routing and evidence records. Do not create a second orchestrator or turn natural-language eligibility into unrestricted permission. Prompt-only fixes cannot correct stale controller ownership; a new resolver subsystem is unnecessary.

## 1. Issue identity and lifecycle

Use an immutable selection identity formed from run ID, original issue fingerprint and selection revision. Preserve the issue label for presentation, but never use a renumbered `ISS-001` alone as closure authority. Reuse existing fingerprint helpers and ledger storage. Preserve legacy history; keep a durable identity-bound history record before replacing a reused label's current entry.

Lifecycle: selected -> repaired (submission, not approval) -> validated. A submission can instead remain unresolved or unverifiable. A fresh independent SAGE review explicitly identifies the selected issue instance, outcome, reviewed artifacts and rationale. Omission from a report is insufficient. Whole-gate FAIL can coexist with validated individual issues.

The controller owns the review envelope: run/spec identity, selection revision, review dispatch identity, input manifest and hashes. The provider supplies only the typed assessment and evidence references. Validate references against the dispatched manifest; reject path traversal, out-of-scope paths, missing inputs, duplicate/conflicting assessments and identity mismatches. Missing or malformed evidence never closes an issue.

SAGE checks both the selected finding and remaining required findings. Its current register remains authoritative for the aggregate gate. Per-issue closure must not modify the aggregate verdict or remove other findings.

Persist valid SAGE closure through existing attested/CAS state mechanisms after Stage 1, before PLAN2. A subsequent PLAN2 BLOCKED cannot discard closure. Use idempotent review-dispatch identity so restart neither duplicates closure nor replenishes budget. Failed CAS cannot apply a stale routing decision.

Review evidence is content-bound. Capture selected affected artifacts plus relevant requirement/contract dependencies in the review manifest. If downstream regeneration changes those inputs, mark that closure pending revalidation before relying on it. Do not resurrect the old repair instruction solely because validation is pending: re-review first. Existing files, an agent COMPLETE verdict, mtime changes, or an aggregate score are not closure evidence.

## 2. Repair context

Initial architecture creation remains unchanged. For a selected repair or a current controller-routed WHY3 repair, append a controller-owned repair package containing:

- Current issue identity, classification, owner, action and scope limits.
- The relevant current issue body and affected artifact contents, including referenced task/contract checklists.
- Evidence sources, unresolved evidence needs, previous submission and review feedback.
- Current requirement-preservation and authority constraints.

Paths resolve against the declared run-local spec and permitted read-only implementation targets, not a guessed published spec. Required repair sections are budgeted explicitly. If they cannot fit or be read, block with `repair_context_incomplete`, naming the unavailable inputs; never silently dispatch a context-starved retry. Use existing bounded rendering and context reports.

Only the active issue instance can inject selected-repair instructions. A validated selection is cleared atomically; unrelated invocations must not inherit its instruction. Repaired selections awaiting review receive validation context only at the reviewer, not another worker instruction to reimplement the same repair.

Fix repeated same-key journal selectors to mean OR within a key and AND between different keys; preserve existing single selectors and wildcard matching. Include current consensus challenges for a repair. Journal history supplements the explicit repair package and never substitutes for it.

## 3. Work assignment versus decision acceptance

Add a versioned Phase 3 action assessment to the existing prepared SAGE result, not agent-writable controller state:

- `apply_evidenced_resolution`: preserve existing exact eligible-option decision semantics.
- `investigate_or_design`: the existing owner must inspect sources and produce a bounded technical proposal/repair, not accept a conjecture as fact.
- `human_decision`: existing authority/approval flow.
- `external_prerequisite`: a named unavailable prerequisite with actionable next steps; do not pretend investigation can supply it.

Each assessment binds the current issue instance, declared owner phase, affected paths, evidence references, concrete action and constraints. Controller checks syntax, provenance and the existing owner allowlist. The owner can read declared sources and modify only its existing owned spec artifacts. Cross-owner changes require a handoff through existing phases; a payload cannot expand writable roots.

For `investigate_or_design`, distinguish verified facts from proposed choices. Require rationale and explicit preservation of validated scope, behavior and acceptance requirements. Proposed measurement mechanisms may operationalize a criterion but cannot lower it. If the proposal changes product scope, protected policy or requirement strength, route through existing decision/spec-revision authority. No automatic approval of security/privacy/legal/safety policy or irreversible commitments.

SAGE instructions must not treat every value absent from sources as human-owned: an agent can be assigned to derive evidence or propose a technical mechanism. This does not make an unevidenced answer eligible for automatic adoption. Independent SAGE validation remains required after the owner submits its work.

Existing `Banzai eligible: no` retains its meaning for answer adoption. Legacy contradictory guidance triggers at most one persisted SAGE action-assessment retry per issue identity and input fingerprint, using the current issue and sources. This is a narrowly scoped request to the existing reviewer, not a new workflow agent. Ambiguous or invalid output ends with an explicit classification/authority blocker, not an assumed grant of permission. No repeated reclassification from identical inputs.

Automatic work scheduling is limited to banzai Phase 3; shared lifecycle correctness applies wherever a selection already exists. Preserve semi-mode approval semantics and WHY2 autonomous-default contracts.

## 4. Progress, limits and reporting

Record identity, owner, input and affected-artifact fingerprints, action, submission and review outcome in the existing telemetry/evidence surfaces. Never log secrets or entire source files as progress summaries.

No-op COMPLETE submissions consume a repair attempt but do not prove progress or reset any budget. Within a selected issue cycle, two consecutive independently reviewed submissions that leave the selected defect unresolved trigger `repair_no_progress`; existing stricter dispatch/cancellation/token limits take precedence. Compare explicit issue assessments and relevant content, not timestamps, report renumbering, or unrelated formatting changes. If evidence genuinely changes, preserve cumulative attempt use; do not award unlimited cycles.

Terminal reporting names the producer, unresolved issue, owner, attempted action, missing evidence/authority and applicable resume prerequisite. Preserve valid BLOCKED rationale from PLAN2 instead of reducing a detailed handoff to only `agent_blocked`. Do not recommend a blind continue. Monitoring remains read-only until a separately authorized resume.

## 5. Compatibility and phased release

1. Add independent per-issue review, durable closure and repair context. Keep all existing decision permissions. Legacy states without closure receipts require fresh review, not inferred success.
2. Add typed technical work routing and bounded legacy action assessment. Invalid/new payloads fail closed; old valid evidenced-option routes still work.
3. Run deterministic regression suites, review, install and refresh deployed bundles, then resume preserved spec008 through the CLI when authorized. Do not reset it or manually patch demo artifacts.

No live resume until the required fixes are installed together. Preserve uncommitted SOAR-disable and SENTINEL work; do not mix unrelated changes into this fix's commits.

## Acceptance and regression matrix

- Selected A explicitly resolved and B still failing: validate A, clear selection, retain FAIL and route B.
- A omitted without explicit assessment, stale review, missing artifact, identity reuse, malformed assessment, or concurrent state change: no false closure.
- Stage 1 closes A then PLAN2 blocks; crash/restart: A's closure remains durable and is not double-applied.
- PLAN2 or SENTINEL mutates reviewed dependencies: require new validation before relying on closure; never silently reuse stale proof.
- Current issue/checklist reaches the correct owner under both bounded and legacy context modes. Required-context overflow is visible.
- Repeated journal phases select both phases; different-key conjunction and wildcard compatibility hold.
- Banzai technical design reaches existing owner; protected authority, external facts and quality waivers cannot be auto-approved.
- Legacy contradictory guidance is reclassified once; malformed or ambiguous output does not loop or grant permissions.
- Repeated no-op submissions stop with actionable evidence; restart preserves attempts and existing global caps.
- Existing WHY2/proportional, semi, coverage, final readiness, prepared-result integrity and delivery verification tests pass without changing their criteria.

Live success is a complete, independently accepted spec, or an accurate actionable external/owner blocker. Merely starting another repair, generating documents, or passing structural validation is not success. The observed geometry gaps should be assigned as work and reviewed, not answered manually by this assistant.

## Implementation review notes — 2026-09-09

Review receipts cover all existing HOW/SENTINEL/PLAN artifacts, including nested
ADRs. Input freshness is reconciled both on restart and after PLAN2, including
historical issue instances hidden by reused display labels. Receiptless legacy
Phase3 closures require a fresh independent review. Stable internal ledger slots
retain those instances without overwriting the newer finding.

Pending technical work is consumed only while WHY3 fails and the exact finding
remains current. A typed human decision or external prerequisite is an actionable
blocker, not automatic adoption or blind continuation. Evidenced-resolution
classification alone cannot replace the existing eligible-option certificate.

The cross-layer fake-provider regression exercises ARCHITECT work, WHY3 and
ASSESS2 before PLAN2, real deterministic gates and sealed controller transitions.
It verifies A closure, B assignment, restart, final dependency revalidation and
advancement only after independent acceptance.

Installed validation on preserved spec008 independently closed the old enum
repair, revalidated it after PLAN2 changed inputs, and classified the current
geometry work as owner-assigned `investigate_or_design`. It then stopped with
`repair_budget_exhausted` at the unchanged 10/10 iteration limit before dispatching
that new work. The demo specification is not complete; further authoring needs
an explicitly authorized budget extension. No manual demo repair or quality
waiver was used. Detailed regression counts and deployment evidence are in the
implementation plan's current completion checkpoint.
