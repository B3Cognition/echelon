# Constitution Reconciliation Design

**Status:** Approved for implementation planning
**Date:** 2026-07-17
**Owner:** Echelon
**Scope:** Default Phase A constitution verification, amendment approval, application, verification, and replay

## Context

Echelon creates the project constitution early in Phase A from UNDERSTAND
artifacts. Later phases discover stronger evidence from the specification,
source review, feasibility analysis, and architecture work. GATEKEEPER already
flags contradictions between that evidence and the constitution, but the
default workflow does not route those findings back to CHIEF.

The current system has useful pieces without a closed loop:

- CHIEF owns constitution creation and amendment through `speckit.constitution`.
- GATEKEEPER is instructed to flag constitution conflicts.
- The build path enforces the published constitution snapshot.
- An experimental constitution-quality phase can inspect and repair conflicts,
  but it is intentionally excluded from the default Phase A path.
- Build finalization can produce amendment candidates, but promotion is a later
  human-governance process rather than pre-HOW reconciliation.

This permits a stale constitution to remain authoritative after evidence has
refuted it. ARCHITECT and build agents then correctly enforce governance that is
incorrect for the current feature.

## Goals

- Verify constitution consistency after feasibility evidence is available and
  before solution work commits to architecture.
- Give every LLM control output in the reconciliation flow a strict, versioned,
  harness-validated contract.
- Keep semantic judgment with the appropriate agents while keeping state,
  routing, approval policy, hashes, artifact publication, retries, and replay
  deterministic and harness-owned.
- Require human approval for semantic amendments in `guided` and `semi` modes.
- Automatically approve validated semantic amendment proposals in `banzai`
  mode according to harness policy.
- Apply approved amendments only through CHIEF and `speckit.constitution`.
- Verify both the mechanical mutation and semantic conflict resolution before
  publishing an amended snapshot.
- Conservatively replay every downstream phase that consumed the superseded
  constitution.
- Remain recoverable and idempotent across process interruption or context
  compaction.

## Non-Goals

- Do not make Python decide whether two natural-language statements are
  semantically contradictory.
- Do not permit agents to write reconciliation state or choose workflow routes.
- Do not let GATEKEEPER, COMMANDER, ARCHITECT, or the harness directly author
  constitution prose.
- Do not weaken build-time constitution enforcement.
- Do not replace the post-build amendment-candidate learning flow.
- Do not turn the experimental EGR-063 quality phase into the default gate as-is.
- Do not support proceeding past an unresolved blocking constitution conflict.

## Policy Decisions

### Approval policy

The harness derives approval behavior exclusively from the persisted autonomy
mode:

| Autonomy mode | Semantic amendment approval |
|---|---|
| `guided` | Block and request a human decision |
| `semi` | Block and request a human decision |
| `banzai` | Automatically approve the validated proposal |

In banzai, the LLM does not approve its own proposal. The harness records an
approval with `approved_by: autonomy_policy` only after the proposal contract
passes validation and is bound to the active constitution hash.

### Authority boundary

The invariant is:

```text
Agents judge semantics and propose prose.
The harness validates contracts and owns control flow.
CHIEF is the only semantic constitution writer.
```

An LLM result is evidence, not state. The harness derives reconciliation status,
approval, routing, attempts, hashes, publication, and replay from validated
payloads.

### Replay policy

Every successfully applied semantic amendment replays from `phase1-what`, the
earliest downstream phase that consumes constitution governance. Replaying only
ASSESS could leave requirements authored under superseded principles.

## Alternatives Considered

### Promote the experimental constitution-quality phase

This is the smallest apparent change, but it combines detection and repair in
one LLM dispatch, lacks a strict amendment proposal contract, and does not own
deterministic replay. It remains useful for benchmarks but is not sufficient for
the default workflow.

### Contract-led reconciliation controller

This is the selected design. Agents emit typed review, proposal, application,
and verification payloads. A harness controller validates them, records
immutable artifacts, applies autonomy policy, guards mutation, publishes the
snapshot, and replays invalidated phases.

### Fully deterministic semantic checker

Python can validate structure, identity, hashes, exact references, and state
transitions, but it cannot reliably decide whether arbitrary Markdown
governance contradicts feature evidence. A deterministic-only design would
either miss semantic conflicts or encode a brittle domain-specific language.

## High-Level Flow

```text
phase2-decide / GATEKEEPER
        |
        | constitution_review.v1
        v
Harness review validation and routing
        |
        +-- clean or warnings only ----------------> phase2-strategic-overview
        |
        +-- revise_spec ----------------------------> phase1-what
        |
        +-- human_direction
        |      +-- guided/semi ---------------------> block for answer
        |      +-- banzai --------------------------> COMMANDER direction judgment
        |                                                |
        |                                                | constitution_direction.v1
        |                                                v
        |                                           Harness-derived route
        |
        +-- amend_constitution
               v
        CHIEF Proposal mode
               |
               | constitution_amendment_proposal.v1
               v
        Harness approval policy
          +---- guided/semi ------------------------> block for ratification
          +---- banzai -----------------------------> auto-approve
               v
        CHIEF Amendment mode via speckit.constitution
               |
               | constitution_amendment_application.v1
               v
        Harness mutation and metadata checks
               v
        GATEKEEPER read-only verification
               |
               | constitution_verification.v1
               v
        Harness publishes snapshot and replays from phase1-what
```

Normal GATEKEEPER verdicts remain `PASS`, `KILL`, and `DEFER`.
`constitution_review` is an orthogonal required payload. The harness consumes
it for a `PASS` result before evaluating the normal forward transition. `KILL`
remains terminal and `DEFER` retains its existing route to WHAT.

## Workflow Nodes

The default graph gains these nodes:

```text
phase2-constitution-proposal
phase2-constitution-approval
phase2-constitution-amend
phase2-constitution-verify
phase2-constitution-direction
```

- `phase2-constitution-proposal` dispatches CHIEF in non-mutating Proposal mode.
- `phase2-constitution-approval` is harness-internal and never invokes an LLM.
- `phase2-constitution-amend` dispatches CHIEF in Amendment mode.
- `phase2-constitution-verify` dispatches GATEKEEPER in read-only verification
  mode.
- `phase2-constitution-direction` dispatches COMMANDER only when banzai must
  resolve a `human_direction` finding. COMMANDER returns a typed judgment; the
  harness derives the route.

The graph remains declarative. Phase specs own context and output contracts;
agent files own invariant protocols. The command wrapper remains thin.

## Phase-Specific Result Contracts

### Contract selection

Workflow nodes declare additional required result contracts:

```yaml
result_contracts:
  - name: constitution_review
    version: 1
    required: true
```

The harness appends only the applicable phase-specific template after the
global `echelon_result` template. Templates live under:

```text
extension/templates/result-contracts/
  constitution-review-v1.yaml
  constitution-amendment-proposal-v1.yaml
  constitution-amendment-application-v1.yaml
  constitution-verification-v1.yaml
  constitution-direction-v1.yaml
```

Python validators are authoritative. Templates teach agents the form; they are
not the validation implementation.

If a required contract is missing or invalid, the existing single result-repair
dispatch may reconstruct only the control payload. A second failure blocks the
run without applying state updates.

### `constitution_review.v1`

GATEKEEPER always emits the review, including when it is clean:

```yaml
echelon_result:
  verdict: PASS
  output_files:
    - feasibility.md
  state_updates:
    feasibility_structural_pass: true
  constitution_review:
    schema_version: 1
    reconciliation_id: "CR-<harness-generated>"
    constitution_sha256: "sha256:<harness-injected-base-hash>"
    outcome: <clean|conflicts>
    findings:
      - finding_id: "C-001"
        principle:
          reference: "Principle V"
          current_text: "<exact text from the active constitution>"
        classification: <stale_assumption|scope_conflict|governance_conflict|ambiguity>
        severity: <warning|blocking>
        recommended_resolution: <amend_constitution|revise_spec|human_direction>
        evidence:
          - artifact: "spec.md"
            locator: "FR-043"
            excerpt: "<short supporting excerpt>"
        rationale: "<grounded contradiction explanation>"
```

Validation rules:

- `clean` requires `findings: []`.
- `conflicts` requires at least one finding.
- Finding IDs must be unique and match the contract pattern.
- `principle.current_text` must occur in the hashed constitution.
- Evidence artifacts must be present in the harness-generated dispatch manifest.
- Evidence locators must resolve deterministically where the artifact format
  exposes stable IDs.
- Every blocking finding must declare a resolution.
- The echoed reconciliation ID and constitution hash must match the harness
  input.
- GATEKEEPER cannot set reconciliation or routing state through `state_updates`.

Warnings are persisted but do not block by themselves. When several blocking
resolution types are present, deterministic precedence is:

1. `human_direction`
2. `revise_spec`
3. `amend_constitution`

This avoids amending governance while an upstream product decision or spec
revision may remove the conflict.

### `constitution_amendment_proposal.v1`

CHIEF Proposal mode returns semantic operations without modifying files:

```yaml
echelon_result:
  verdict: CHANGES_REQUESTED
  output_files: []
  state_updates: {}
  constitution_amendment_proposal:
    schema_version: 1
    reconciliation_id: "CR-<harness-generated>"
    proposal_id: "CAP-<harness-generated>"
    base_constitution_sha256: "sha256:<base-hash>"
    resolves_findings: ["C-001"]
    summary: "<human-readable amendment intent>"
    operations:
      - operation_id: "OP-001"
        operation: <add|replace|remove>
        principle_reference: "Principle V"
        current_text: "<exact existing text or empty for add>"
        proposed_text: "<replacement/addition or empty for remove>"
        rationale: "<why this resolves the findings>"
        finding_ids: ["C-001"]
```

Validation rules:

- The reconciliation ID, proposal ID, and base hash must match harness-issued
  values.
- Every amendment finding must be covered by at least one operation.
- Every referenced finding must exist in the validated review.
- Operation IDs must be unique.
- `replace` and `remove` require exact current text from the base constitution.
- `add` requires an existing anchor principle and empty `current_text`.
- `add` and `replace` require non-empty proposed text.
- `remove` requires empty proposed text.
- No routing or replay recommendation is accepted from the LLM.
- The pre- and post-dispatch constitution hashes must be identical in Proposal
  mode.

The harness renders canonical `proposal.json` and `proposal.md`. Agent-written
copies are not authoritative.

### `constitution_amendment_application.v1`

After approval, CHIEF Amendment mode invokes `speckit.constitution` and emits:

```yaml
echelon_result:
  verdict: DONE
  output_files:
    - .specify/memory/constitution.md
  state_updates: {}
  constitution_amendment_application:
    schema_version: 1
    reconciliation_id: "CR-..."
    proposal_id: "CAP-..."
    applied_operations: ["OP-001"]
```

The contract intentionally excludes a claimed output hash. The harness computes
the authoritative hash and diff from disk.

### `constitution_verification.v1`

GATEKEEPER verifies the amended constitution without writing it:

```yaml
echelon_result:
  verdict: PASS
  output_files: []
  state_updates: {}
  constitution_verification:
    schema_version: 1
    reconciliation_id: "CR-..."
    proposal_id: "CAP-..."
    outcome: <pass|fail>
    finding_results:
      - finding_id: "C-001"
        status: <resolved|unresolved|regressed>
        rationale: "<evidence-backed result>"
    unintended_changes:
      - principle_reference: "Principle II"
        rationale: "<why this was outside the approved proposal>"
```

`outcome: pass` requires every original amendment finding to appear exactly
once with `status: resolved` and requires `unintended_changes: []`.

### `constitution_direction.v1`

In guided and semi, a `human_direction` finding becomes a typed human blocked
decision. In banzai, COMMANDER may resolve it only through this contract:

```yaml
echelon_result:
  verdict: JUDGMENT_RESOLVED
  output_files: []
  state_updates: {}
  constitution_direction:
    schema_version: 1
    reconciliation_id: "CR-..."
    finding_ids: ["C-003"]
    decision: <amend_constitution|revise_spec>
    rationale: "<grounded best-judgment direction>"
    evidence_refs:
      - artifact: "feasibility.md"
        locator: "C-003"
```

The harness requires exact coverage of every pending `human_direction` finding,
validates evidence against the dispatch manifest, and derives the next phase
from `decision`. COMMANDER cannot return `next_phase` or reconciliation state.

## Harness-Owned State

`constitution_reconciliation` becomes a reserved state key. Any agent attempt
to set it through `state_updates` is rejected.

State contains a bounded summary and pointers, not duplicate LLM payloads:

```json
{
  "constitution_reconciliation": {
    "schema_version": 1,
    "reconciliation_id": "CR-...",
    "status": "awaiting_approval",
    "source_phase": "phase2-decide",
    "base_constitution_sha256": "sha256:...",
    "review_path": "runs/.../review.json",
    "proposal_id": "CAP-...",
    "proposal_path": "runs/.../proposal.json",
    "approval_path": null,
    "application_attempts": 0,
    "verification_attempts": 0,
    "replay_from": "phase1-what"
  }
}
```

Canonical reconciliation records are immutable files:

```text
runs/<run-id>/constitution-reconciliation/<reconciliation-id>/
  manifest.json
  review.json
  proposal.json
  proposal.md
  approval.json
  application.json
  constitution-before.md
  constitution-after.md
  amendment.diff
  verification.json
  invalidated-manifest.json
  invalidated/
```

The harness writes JSON canonically with stable key ordering and atomic replace.
Timestamps, identifiers, and hashes are harness-generated.

## Reconciliation State Machine

```text
review_pending
  -> clean
  -> proposal_pending
  -> awaiting_approval
  -> approved
  -> applying
  -> verifying
  -> verified
  -> replaying
  -> clean
```

Failure states are:

```text
invalid_review
stale_proposal
application_failed
verification_failed
non_convergent
```

Only the reconciliation controller changes these states. Each transition is
persisted before the next side effect so recovery can distinguish work not
started from work partially completed.

## Approval and Resume

### Guided and semi

The harness writes a typed blocked decision:

```json
{
  "decision_kind": "constitution_semantic_amendment",
  "requires_human": true,
  "proposal_id": "CAP-...",
  "base_constitution_sha256": "sha256:...",
  "options": [
    {
      "id": "approve_amendment",
      "label": "Approve amendment",
      "action": "approve_constitution_amendment",
      "subject_id": "CAP-..."
    },
    {
      "id": "request_changes",
      "label": "Request proposal changes",
      "action": "revise_constitution_proposal",
      "subject_id": "CAP-..."
    },
    {
      "id": "reject_and_revise_spec",
      "label": "Reject and revise feature",
      "action": "reject_constitution_amendment",
      "subject_id": "CAP-...",
      "next_phase": "phase1-what"
    }
  ]
}
```

The escalation option schema gains `action` and `subject_id`. Resume accepts an
option selector followed by detail:

```bash
echelon spec resume "B: Keep PostgreSQL as the preferred store, not a mandatory one."
```

The harness parses the selector deterministically and preserves the remainder
as the human instruction. It does not ask an LLM to infer the selected option.

There is no `proceed despite conflict` option.

### Banzai

Banzai does not enter the human blocked state. After proposal validation, the
harness writes:

```json
{
  "schema_version": 1,
  "proposal_id": "CAP-...",
  "base_constitution_sha256": "sha256:...",
  "decision": "approved",
  "approved_by": "autonomy_policy",
  "autonomy_mode": "banzai",
  "approved_at": "<harness timestamp>"
}
```

Automatic approval applies to any valid semantic amendment proposal. It does
not waive proposal validation, hash binding, mutation checks, semantic
verification, bounded retries, or convergence limits.

## Mutation Guard

Before Amendment mode, the harness records:

- Exact constitution bytes and hash.
- Proposal and approval identity.
- Git status paths and hashes for pre-existing dirty paths.
- The sole allowed mutation path: `.specify/memory/constitution.md`.
- Approved operations and expected before/after text.

After CHIEF returns, the harness compares the repository to the pre-dispatch
baseline. It rejects the application when:

- The base constitution changed before dispatch.
- Any path outside the allowed mutation set changed relative to the baseline.
- A pre-existing dirty file was changed further by the dispatch.
- Approved current text remains when it should be replaced or removed.
- Approved proposed text is absent.
- An unapproved constitution section changed.
- Template markers appear.
- The semantic version did not increase.
- The ratification date changed.
- The last-amended date was not updated.
- The application payload omits an approved operation.

The mutation guard must tolerate unrelated user changes that existed before the
dispatch while detecting new or additional changes. It records hashes for all
pre-dirty paths and compares the pre/post status path sets.

On failure, the harness restores only the constitution from its saved preimage.
It never resets or checks out unrelated user files.

The harness saves `constitution-after.md` and `amendment.diff` before semantic
verification. Failed application never updates a published snapshot.

## Snapshot Publication

After deterministic mutation checks and semantic verification both pass, the
harness atomically republishes the canonical constitution to every active Phase
A `constitution.md` snapshot location known by run state.

Publication uses write-to-sibling plus `os.replace`, then verifies the target
hash equals the canonical hash. A publication failure blocks before replay. The
canonical `.specify/memory/constitution.md` remains authoritative and the state
records which snapshot failed.

## Replay and Artifact Invalidation

### Replay frontier

The replay frontier for every successful semantic amendment is always
`phase1-what`. The harness preserves UNDERSTAND artifacts and the amended
constitution, invalidates downstream completion state, and resumes
CARTOGRAPHER in amendment/replay mode.

### Managed artifacts

Artifact invalidation must not parse human-readable `outputs` descriptions.
Workflow nodes gain explicit deterministic metadata:

```yaml
managed_artifacts:
  - path: spec.md
    on_invalidate: archive_preserve
  - path: issues.md
    on_invalidate: archive_remove
  - path: quality-gates.md
    on_invalidate: archive_remove
```

Supported policies are:

- `archive_remove`: copy the current artifact into the reconciliation archive,
  then remove its active copy.
- `archive_preserve`: archive the current artifact but leave it in place as the
  base for amendment-mode regeneration.
- `retain`: keep the artifact and record that it survived invalidation.

Paths must be relative to the active spec directory. Absolute paths, traversal,
and symlink escapes are rejected. Wildcards are resolved only below that root.

`spec.md` uses `archive_preserve` so CARTOGRAPHER sees an existing specification
and follows its resumed/amendment protocol instead of invoking first-pass spec
creation again.

### State invalidation

The harness:

1. Archives managed artifacts from the replay frontier onward.
2. Applies each artifact's invalidation policy.
3. Removes affected phases from `completed_phases`.
4. Clears their dispatch counts and phase-derived gate state.
5. Sets `phase` to `phase1-what` and `status` to `running`.
6. Attaches the reconciliation report and amended constitution hash to the
   replay context.
7. Continues automatically.

Rejecting an amendment and revising the feature uses the same frontier but
records the rejection and human rationale in the replay context.

## Convergence and Failure Handling

Default configuration:

```yaml
constitution_reconciliation:
  enabled: true
  max_cycles: 2
  max_proposal_attempts: 2
  max_application_attempts: 2
  max_verification_attempts: 2
```

Policies:

- Invalid review or proposal payload: one control-payload repair dispatch, then
  block.
- Stale proposal or approval: regenerate against the current constitution.
- Application mismatch: restore the constitution preimage and retry within the
  configured limit.
- Semantic verification failure: return to Proposal mode with verification
  findings.
- The same normalized conflict after two full cycles: set `non_convergent` and
  block, including in banzai.
- Unexpected file mutation: restore the constitution preimage, preserve the
  evidence, and block immediately.
- Snapshot publication failure: block before replay and retain the verified
  canonical constitution.

Conflict normalization uses classification, principle reference, and sorted
evidence locators. It does not compare rationale prose.

## Crash and Resume Recovery

Reconciliation composes with the existing `last_dispatch` sentinel. The
controller persists its transition before every external dispatch or mutation.

Recovery behavior:

- `awaiting_approval`: remain blocked with the same typed decision.
- `approved`: dispatch Amendment mode.
- `applying` with the base hash unchanged: retry application.
- `applying` with a changed hash but no application record: run deterministic
  post-application checks instead of applying twice.
- `verifying`: redispatch the read-only verifier.
- `verified`: publish snapshots if needed.
- `replaying`: repeat idempotent invalidation and continue at `phase1-what`.

Every recovery checks reconciliation ID, proposal ID, and hashes before acting.

## Observability

The harness prints concise reconciliation banners containing:

- Reconciliation and proposal IDs.
- Conflict count and blocking count.
- Approval source (`user` or `autonomy_policy`).
- Old and new constitution hashes.
- Application and verification attempts.
- Replay frontier.

The final squad report links the human-readable proposal, approval record,
verification record, and invalidated artifact manifest. Journal entries record
semantic findings, but journal content never drives routing.

## Implementation Boundaries

Expected implementation areas:

- Create `src/harness/constitution_reconciliation.py` for controller state,
  immutable records, approval policy, mutation guarding, publication, and
  recovery.
- Create `src/harness/constitution_result_contracts.py` for the five strict
  payload validators.
- Extend `src/harness/echelon_result_schema.py` to recognize and validate known
  phase-specific payloads while retaining phase-required validation in the
  executor.
- Extend `src/harness/phase_graph.py` and workflow validation for
  `result_contracts` and `managed_artifacts`.
- Extend `src/harness/squad_executors.py` to append phase-specific templates and
  reject missing required contracts before state mutation.
- Integrate the reconciliation controller into `src/harness/squad.py` before
  normal `phase2-decide` PASS routing.
- Extend `src/harness/blocked_decision.py` and `src/echelon/cli.py` for typed
  approval actions and selector-plus-detail resume answers.
- Add the four workflow phase specs and update `extension/workflow/definition.yaml`.
- Add CHIEF Proposal mode and GATEKEEPER Verification mode without duplicating
  their invariant protocols into phase specs.
- Add result-contract templates and configuration defaults.
- Update the artifact index and final report to expose reconciliation records.

The implementation should reuse the existing atomic squad state store, result
repair behavior, typed blocked decisions, and rewind-state patterns. It must not
reuse branch-reset rewind for automatic reconciliation because that operation
would be destructive to unrelated working-tree changes.

## Testing Strategy

### Unit tests

- All five result-contract validators.
- Cross-field invariants and exhaustive finding coverage.
- Contract ID and hash echo validation.
- Deterministic routing precedence for mixed findings.
- Guided/semi blocking versus banzai automatic approval.
- Stale proposal and approval rejection.
- Structured resume actions and `B: detail` parsing.
- Mutation guard with clean and pre-dirty worktrees.
- Detection of new changes to pre-existing dirty files.
- Exact-operation, version, amendment-date, and ratification-date checks.
- Constitution preimage restoration.
- Managed-artifact containment, policies, and invalidation calculation.
- State-machine recovery from every persisted status.
- Conflict normalization and convergence limits.

### Integration tests

- A clean review proceeds without a proposal.
- Guided and semi stop, approve, apply, verify, publish, and replay.
- Banzai completes the same flow without entering a human block.
- Human proposal rejection routes to `phase1-what`.
- Requested changes regenerate the proposal without modifying the constitution.
- Mixed `human_direction`, `revise_spec`, and amendment findings follow the
  deterministic precedence.
- Malformed LLM output cannot mutate state or approve an amendment.
- Unexpected CHIEF file writes are rejected without disturbing user changes.
- Crash after approval, mutation, verification, publication, and invalidation
  resumes idempotently.
- Repeated normalized conflict reaches bounded non-convergence.

### Contract and static tests

- Every reconciliation phase declares the correct result contract.
- Generated prompts contain the exact applicable phase-specific schema.
- CHIEF Proposal mode forbids writes and skill invocation.
- CHIEF Amendment mode requires `speckit.constitution`.
- GATEKEEPER verification is read-only.
- No phase permits `constitution_reconciliation` in agent `state_updates`.
- Managed artifact paths remain spec-contained.
- The default graph gates solution work on completed reconciliation.

## Rollout and Compatibility

The reconciliation gate is enabled by default for new Phase A runs. Existing
completed runs are not retroactively reopened. A resumed run that reaches
`phase2-decide` uses the new gate and initializes reconciliation state lazily.

The experimental constitution-quality phase remains available for benchmark
variants. It may reuse the new validators later, but it does not replace or
bypass the default reconciliation controller.

If the feature is temporarily disabled in configuration for rollback, the
harness records a visible warning that semantic constitution reconciliation was
skipped. Build-time enforcement remains unchanged.

## Self-Review

- The design contains no placeholder or unresolved implementation decision.
- Approval behavior is explicit for all autonomy modes.
- LLM outputs are strict contracts; none can directly mutate reconciliation
  state or route the workflow.
- Mutation, publication, replay, retry, and recovery ownership all reside in
  the harness.
- The replay frontier is conservative and preserves `spec.md` for amendment
  mode.
- Failure handling is bounded and does not authorize destructive cleanup of
  unrelated user changes.
