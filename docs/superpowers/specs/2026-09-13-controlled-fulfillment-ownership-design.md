# Controlled fulfillment ownership: phased design

Status: approved design; inactive Phase 1 preparation implemented and reviewed
on 2026-09-14. Phases 2–4 are not implemented by this checkpoint.
Baseline: `bffbf46b` on `fix/delivery-controller-contract`.

## Purpose and authorization

Close the remaining model-owned fulfillment sequencing in active controlled
delivery. The user approved preparing this phased design after the PR-review
re-entry checkpoint. This document does not authorize installation, live models,
rollout, identity activation, or a replacement fulfillment subsystem.

The invariant is the original goal: Python owns invocation-specific orchestration;
Prosaic supplies neutral semantic roles. There is no extra COMMANDER role and no
new "when run from delivery" branch in shared role prose.

## Existing boundary and reuse

`src/harness/fulfillment_runner.py` already owns admission, full/scoped selection,
cache checks, run initialization, coverage-observation binding, report validation,
freshness stamping, ledger reuse and portions of lifecycle/reconciliation.
Its remaining model path calls `_build_verify_spec_prompt`, loading
`echelon.verify-spec` plus `verify-spec-*.md` companions. The resulting COMMANDER
prompt asks the model to execute deterministic helpers, dispatch a mapper,
dispatch SPEC-GUARD when necessary, and advance phases.

The full and scoped branches are not identical. Full refresh has a deterministic
no-fallback shortcut. Scoped refresh calculates impacted IDs, may fall back to
full refresh, snapshots the base report, and merges changed rows. Neither path
may be replaced by a superficially equivalent full-only implementation.

Two callers construct `FulfillmentRunner`: Ralph and the standalone authoritative
spec-verification CLI in `src/echelon/cli_app.py`. The latter is not silently
migrated by this delivery checkpoint.

### Chosen approach

Extend the existing runner with an explicitly selected controlled execution path.
Use small fulfillment-specific helpers for preparation, semantic result validation
and recovery where that keeps the runner readable. Existing deterministic writers
and parsers remain authoritative; do not duplicate their algorithms.

Alternatives considered:

- Prose-only clarification leaves sequencing with the model and does not close
  the ownership problem.
- A new workflow engine or independent publisher duplicates existing ownership
  and expands convergence scope. It is excluded.

## Ownership and execution sequence

| Step | Owner and existing implementation to reuse |
| --- | --- |
| Admission and context | `FulfillmentRunner`: exact spec/source/workspace/run binding, scope, receipt and observer checks, cache/ledger policy |
| Run lifecycle | `verify_spec_run.init_verify_spec_run`, `block_verify_spec_run`, `complete_verify_spec_run`; reuse the selected run, never infer another from "latest" during recovery |
| Structural evidence | `codegraph_evidence.write_codegraph_evidence`, `perlgraph_evidence.write_perlgraph_evidence`, then `topology_evidence.write_topology_evidence_receipt` |
| Requirement/product inventory | `canonical_requirements.write_canonical_requirements`, `product_inventory.write_product_inventory`, `canonical_requirements.write_requirement_audit` |
| Mapping preparation | `coverage_evidence.write_coverage_evidence`, `codegraph_evidence_mapper.write_codegraph_evidence_map` plus existing degraded-map/state behavior |
| Semantic mapping | One neutral fulfillment mapper request, validated and materialized by Python as `implementation-map.md` schema version 2 |
| Mechanical judgment | `judgment_prepass.write_judgment_prepass`; host selects the exact fallback IDs |
| Semantic judgment | A separate neutral fulfillment judge request only when fallback IDs remain |
| Report and completion | Existing report assembler, deferred-scope validation, full/scoped row validation, scoped merge, optional reconciliation, topology/lifecycle completion, stamping and verified ledger |

Some CLI wrappers in `src/harness/__main__.py` own required state stamps and
degraded-map behavior in addition to invoking writers. Extract the minimum shared
callable where necessary and have both callers reuse it; calling a low-level
writer alone must not lose that behavior. Do not shell out to the Echelon CLI
through an LLM or redesign the CLI command surface.

Structural-tool degradation retains its existing explicit evidence status; it
does not itself prove missing implementation. Other missing/invalid prerequisites
block before the dependent model call. Required observer evidence cannot be
replaced by source confidence or a model's statement that tests passed.

## Neutral semantic contracts

Use two focused Prosaic subagents: `echelon.fulfillment-mapper` and
`echelon.fulfillment-judge`. They are fulfillment specialists, not coordinators.
Transfer applicable evidence rules from the current mapping/judgment phases;
leave shared `implementation-mapper`, `spec-guard`, the generic verify-spec command
and legacy phase prose intact for their remaining callers.

The mapper preserves the canonical IDs, deterministic candidate leads,
dispositions, evidence kinds/strengths, runtime-threshold flags and confidence.
Manual inspection is limited to the prepared fallback queue and cited evidence
that needs checking. Active owner-deferred IDs remain mechanically owned.
The host renders the existing ten-column implementation-map schema; separate
unmapped-candidate notes cannot introduce requirement rows.

The judge receives only the unresolved IDs selected by the prepass within the
current scope. It returns one existing fulfillment status and concrete evidence
per assigned ID. It cannot overwrite mechanical/observed-coverage/owner-deferred
decisions. `TASK-PROGRESS` remains the sole existing synthetic report exception;
the host derives its eligibility from progress-integrity evidence, not model
permission to invent a row. Preserve actionable gap and task/test-case context.

Both calls return strict, versioned JSON envelopes bound to the run, step,
dispatch, input fingerprint and exact assigned IDs. Envelopes carry structured
rows and notes, not model-created paths or whole workflow commands. Python
validates duplicates, omissions, enums, field types and row boundaries before
rendering existing Markdown artifacts. No model writes canonical reports, state,
task progress or verification receipts; no completion markers or agent dispatch.

Resolve role bodies/metadata through `ProsaicPromptLoader`, then use the existing
provider facade's `run_agent_result` and enforced read-only review capability.
Use exclusive empty write scope, explicit permitted read roots and the existing
containment policy. Never load `.claude/agents`, read developer AGENTS.md/CLAUDE.md
as runtime instructions, or construct native provider commands in fulfillment.
Claude and Codex must both pass capability/containment tests on the accepted
macOS boundary. Read-only filesystem permissions do not alone prove that arbitrary
shell execution or network is disabled: retain adapter tool controls and verify
the actual dispatched profile, including prohibiting agent dispatch and test runs.
If the current capability cannot enforce the required profile, stop for an explicit
adapter-boundary decision instead of weakening it or adding a hidden fallback.

## State, publication, failures and usage

Keep recovery records local to the existing verify-spec run, using existing
atomic JSON utilities. Record intent before each semantic dispatch, validated
completion afterward, and bind receipts to scope, spec/product inputs, evidence,
role content and provider execution profile. Do not force fulfillment into the
task-slice journal's task-specific schema or introduce a generic journal framework.

Completed, unchanged receipts can be reused without a model call. Unknown external
completion, changed inputs, corrupt receipts or unrecognized legacy in-flight
state require reconciliation; do not replay the call, reset allowances or rewrite
history. Deterministic preparation may be repeated only where idempotence and
input binding are verified. No new automatic semantic repair loop is introduced;
invalid output or an explicit model block returns to Ralph's existing policy.

Stage host-rendered map/fallback/report/gaps output in the selected run, validate
before canonical publication, and retain the previous canonical report until the
new result is accepted. Record exact pending publication bytes/hashes before
writing report/gaps, so interruption cannot produce an accepted mixed generation.
Replay matching pending writes only; conflicting external edits block. The ledger
and final lifecycle status must not advance until publication is complete. This
is a fulfillment-local checkpoint, not a second cross-system publisher.

Account every semantic call, including unsuccessful calls, using reported usage
and the existing explicit unknown-usage convention. Return cumulative operation
usage and newly unaccounted usage separately enough for Ralph to persist a single
charge. Do not rely on the facade's last-call counter, which resets per call.
Enforce remaining budget before dispatch; receipt replay and deterministic/cache
paths add no model usage. Interrupted usage reconciliation must be tested at the
runner-to-Ralph boundary, not only within a helper.

## Compatibility and activation

- Select controlled fulfillment only when Ralph has
  `llm.features.delivery_gate_controller: true`, via an explicit runner option
  defaulting to legacy behavior for other callers. No new public configuration
  flag and no default change.
- Keep feature-off delivery and standalone spec verification on their existing
  contracts. The new controlled path must never fall back to COMMANDER execution.
- Preserve full/scoped planning, unaffected scoped rows, full fallback, cache and
  ledger acceptance rules, reconciliation/dry-run rules, canonical file formats,
  exact IDs, topology degradation and strict observer semantics. Add a controlled
  contract identity to cache/receipt binding where execution semantics differ;
  do not silently relabel legacy cached evidence as newly controlled evidence.
- Preserve banzai/semi/guided policy. Banzai may retain existing refresh deferral
  scheduling, but cannot bypass required fulfillment evidence before convergence.
- Retain identity guards and existing six-digit/unbounded ID compatibility. No
  allocation, lifecycle-authoring or graph/history expansion belongs here.

## Phases and testable exits

Each phase gets a scoped commit and review checkpoint. The controlled route is
not wired into active delivery until all required full/scoped/recovery pieces pass.

1. **Deterministic preparation.** Capture current full/scoped contracts in tests;
   factor reusable preparation with existing state transitions. Prove explicit
   source/spec/run binding, helper order, degraded graph behavior, observer
   handling, and zero model dispatch on invalid prerequisites. Legacy regression
   tests remain green. No active migration yet.
2. **Semantic roles and full refresh.** Add the two neutral roles and strict
   result validation; connect preparation, mapper, prepass, optional judge and
   existing report assembly in the controlled runner. Test mechanical no-judge
   cases, real schema consumers, invalid/missing/extra IDs, forbidden writes,
   evidence semantics, both provider facades and actual adapter profiles.
3. **Scoped completion and recovery.** Connect the same controlled sequence to
   impacted-ID planning/full fallback and existing scoped merge. Complete durable
   semantic receipts, publication recovery and usage accounting. Test unchanged
   rows, deferrals, provenance, cache separation, interruption at each durable
   boundary, no redispatch of completed work, conflicts and budget exhaustion.
4. **Ralph integration and closure.** Wire the existing opt-in, carry usage and
   failure evidence through real Ralph verification/repair, and test all three
   modes with Claude and Codex. Include full/scoped and no-fallback/cache paths,
   non-passing fulfillment, restart, and a completed PR-fix batch through
   verification and post-verification effects. Run legacy/direct-CLI regressions
   and repeat the active prompt-ownership audit before declaring this gap closed.

External model processes and graph/PR services may be scripted, but do not mock
the controller/runner decisions under acceptance. Distinguish real local verifier
execution from scripted execution explicitly. Installation, deployed-bundle refresh,
live-provider acceptance and branch-wide merge verification remain later gates.

## Review decision

The requested next implementation checkpoint is Phase 1 only. Approval of this
design fixes the intended end state and compatibility boundaries; it does not
authorize silently widening a phase when a missing capability is discovered.
The approved Phase 1 implementation plan is
`docs/superpowers/plans/2026-09-13-fulfillment-preparation.md`; its executed
checkpoint records 285 passing affected tests and the independent review.
Shared CLI preparation steps and the bound callable are implemented; no active
runner invokes that callable. Semantic execution, recovery, provider acceptance
and delivery integration remain the separate phases above.
