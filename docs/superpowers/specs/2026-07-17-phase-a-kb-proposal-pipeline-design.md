# Phase A KB Proposal Pipeline Design

**Status:** Approved design
**Date:** 2026-07-17
**Scope:** Phase A `echelon spec run` knowledge-base learning

## Problem

Phase A currently treats `knowledge-base/` as both semantic memory and mutable
runtime state. Learning agents are instructed to read and write canonical YAML
files directly, while some deterministic scripts provide locking, append-only
checks, schema checks, and pending merge support. The result is a mixed ownership
model:

- LLM agents decide what a learning means.
- LLM agents may also mutate canonical memory files.
- The harness can validate some files, but validation is not the sole write path.
- Startup banners and later runs depend on YAML remaining parseable.
- Benefit measurement is mostly inferred from calibration artifacts rather than
  recorded as first-class usage and application evidence.

This is weaker than the newer Echelon pattern used elsewhere: LLMs produce
bounded artifacts and `echelon_result` payloads, while deterministic harness code
parses, validates, applies, and measures the outcome.

The Phase A knowledge base needs the same split. LLMs should own semantics.
The system should own contracts, mutation, recovery, deduplication, and metrics.

## Goals

- Move Phase A learning writes from direct canonical YAML mutation to run-local
  KB proposal artifacts.
- Keep LLM agents responsible for semantic classification: pattern, pitfall,
  SAGE decision, calibration observation, and internalization observation.
- Make every LLM learning output follow a typed proposal template.
- Add deterministic `echelon kb validate` and `echelon kb apply` commands for
  proposal validation and canonical KB mutation.
- Preserve an audit trail from canonical KB entry back to proposal, run, agent,
  source artifacts, and evidence references.
- Keep canonical `knowledge-base/*.yaml` parseable and schema-valid after every
  deterministic apply.
- Record KB usage and apply metrics so later runs can measure whether prior
  knowledge was actually beneficial.
- Keep KB read, proposal, validation, and apply failures non-blocking for the
  user-requested Phase A run. KB failures must be recorded and degraded, not stop
  agents or harness progress.

## Non-Goals

- Do not redesign Phase B, harness build, or codegen KB behavior in this pass.
- Do not introduce semantic truth checking in the harness. The harness validates
  shape, provenance, safety, target compatibility, and deterministic consistency.
- Do not build a global cross-project sync implementation in this pass.
- Do not require every rejected proposal to block Phase A finalization.
- Do not make KB unavailability, malformed proposals, failed usage recording, or
  apply failures block agent dispatch, phase transitions, or finalization.
- Do not delete or rewrite existing legacy KB entries as part of the first pass.
- Do not remove `knowledge-base/` as the canonical durable store.

## Core Boundary

Phase A KB learning becomes a two-step pipeline:

```text
LLM semantic proposal
  -> run-local proposal artifact
  -> deterministic validate/apply
  -> canonical knowledge-base YAML
  -> apply report and usage metrics
```

Agents may propose durable knowledge. Agents do not directly mutate canonical KB
files during Phase A.

The rule is:

```text
LLM can say what something means.
SYSTEM decides whether it is valid memory and how it lands.
KB failure records and degrades; it does not block the product run.
```

Knowledge is an accelerator, not a prerequisite. If KB read, usage recording,
proposal validation, or proposal apply fails, COMMANDER records the failure and
continues with the best available context. Agents receive empty, stale, or
read-only KB context rather than being stopped.

## Run-Local Layout

Each Phase A run gets a proposal directory:

```text
runs/<run-id>/kb-proposals/
  kb-prop-0001.yaml
  kb-prop-0002.yaml
  ...
```

The deterministic apply step writes:

```text
runs/<run-id>/kb-apply-report.yaml
runs/<run-id>/kb-usage.yaml
```

`kb-apply-report.yaml` is the authoritative record of which proposals were
accepted, rejected, skipped, queued, or marked for review.

`kb-usage.yaml` records which existing KB entries were loaded into Phase A
context packs, which agents received them, and whether those entries were cited
or acted on by later outputs.

If usage recording fails, the harness records `kb_usage_status: degraded` in
state and continues dispatch. Missing usage data lowers measurement confidence;
it does not invalidate the run.

## Proposal Contract

Each proposal is one YAML document. The common envelope is:

```yaml
schema_version: 1
proposal_id: kb-prop-0001
proposal_type: pattern
run_id: squad-1234567890
agent: speckit-echelon-mirror
created_at: 2026-07-17T12:00:00Z
target: knowledge-base/patterns.yaml
confidence: 0.72
source_artifacts:
  - runs/squad-1234567890/reasoning-journal.jsonl
  - specs/001-feature/quality-gates.md
evidence_refs:
  - artifact: specs/001-feature/quality-gates.md
    locator: "WHY3"
    claim: "Spec passed validation after the architecture constraint was added."
payload:
  {}
```

Common validation rules:

- `schema_version` must be supported.
- `proposal_id` must be unique within the run.
- `proposal_type` must be one of the supported Phase A types.
- `run_id` must match the active run.
- `created_at` must be an ISO-8601 date-time.
- `agent` must be a known Phase A agent or an explicitly allowed command.
- `target` must be compatible with `proposal_type`.
- `confidence` must be between 0.0 and 1.0 when present.
- `source_artifacts` must exist or be listed as archived run artifacts.
- `evidence_refs` must be non-empty for durable learning proposals.
- `payload` must validate against the type-specific schema.

The harness does not judge whether a semantic claim is wise. It does reject
claims that are unsupported, malformed, unsafe, incompatible with the target, or
impossible to trace.

## Initial Proposal Types

### sage_decision

Target:

```text
knowledge-base/sage-decisions.yaml
```

Purpose:

Record SAGE pass/fail decisions without allowing direct YAML edits to corrupt
the rolling decision log.

Payload shape:

```yaml
artifact: specs/001-feature/spec.md
challenge_type: logical_inconsistency
challenge_summary: "Requirement FR-003 contradicted boundary B-002."
outcome: blocked
resolution: "WHAT revised FR-003 to respect the boundary."
was_correct: true
```

The apply engine writes block scalars where needed and enforces the rolling
`max_entries` cap.

### pattern

Target:

```text
knowledge-base/patterns.yaml
```

Purpose:

Record a reusable successful approach discovered during Phase A.

Payload shape:

```yaml
name: "Architecture constraint before estimates"
domain: "planning"
evidence_grade: C
validated_by_feedback: false
description: "Apply explicit architecture constraints before ASSESS estimates."
tags: ["planning", "calibration"]
status: active
project_fingerprint: auto
scope: local_only
```

The harness computes or verifies `project_fingerprint`. New entries default to
`scope: local_only`. Global promotion remains out of scope for this first pass
unless submitted as `needs_review`.

### pitfall

Target:

```text
knowledge-base/pitfalls.yaml
```

Purpose:

Record a repeatable failure mode with concrete avoidance guidance.

Payload shape:

```yaml
name: "Estimate before boundary resolution"
domain: "planning"
trigger: "ASSESS estimates while unresolved boundary issues remain."
impact: "Effort estimates drift because integration scope is unknown."
avoidance: "Resolve CRITICAL/HIGH boundary questions before effort scoring."
tags: ["planning", "estimation"]
status: active
project_fingerprint: auto
scope: local_only
```

### calibration_observation

Targets:

```text
knowledge-base/calibration-profile.yaml
knowledge-base/estimates-log.yaml
```

Purpose:

Record estimate, confidence, quality-score, or feedback observations that can
update calibration deterministically.

Payload shape:

```yaml
domain: "backend"
observation_kind: estimate_delta
estimate_hours: 8.0
actual_hours: 12.0
confidence: 0.68
quality_score: null
source: "AUDITOR"
```

The apply engine decides whether the observation appends to `estimates-log.yaml`,
updates calibration aggregates, or is marked `needs_review`.

### internalization_observation

Targets:

```text
knowledge-base/internalization-log.yaml
knowledge-base/agent-scores.yaml
knowledge-base/evolution-signals.yaml
```

Purpose:

Record Phase A internalization metric outputs or metric inputs when sufficient
evidence exists.

Payload shape:

```yaml
subject_agent: speckit-echelon-what
agent_tier: deep
prompt_version: v1.0.0
metrics:
  int_I01_requirement_coverage_rate: 0.82
  int_I02_constraint_adherence_score: 0.90
gate_verdict: PASS
computation_health:
  inputs_available: 2
  inputs_missing: 14
  formulas_valid: 2
  formulas_failed: 0
```

Empty or insufficient-data observations are valid no-ops when they preserve the
distinction between `null` and zero.

## Templates

Add templates under:

```text
extension/templates/kb-proposals/
  sage-decision-proposal-template.yaml
  pattern-proposal-template.yaml
  pitfall-proposal-template.yaml
  calibration-observation-proposal-template.yaml
  internalization-observation-proposal-template.yaml
```

Phase A learning agents receive the relevant template in their context pack.
Agent prompts must say:

- write proposal artifacts under `runs/<run-id>/kb-proposals/`
- do not edit canonical `knowledge-base/*.yaml`
- return proposal paths in `echelon_result.output_files`
- use one proposal per semantic learning item

## Deterministic Commands

### `echelon kb validate`

Proposed interface:

```bash
echelon kb validate --run-id <run-id>
```

Responsibilities:

1. Locate `runs/<run-id>/kb-proposals/`.
2. Parse every proposal as YAML.
3. Validate common envelope and type-specific payload.
4. Validate target/type compatibility.
5. Validate proposal IDs are unique.
6. Validate source artifact references.
7. Validate canonical KB files are parseable before apply.
8. Write validation findings to stdout and optionally JSON/YAML with `--output`.

Exit behavior:

- `0`: all proposals valid or only skippable duplicates.
- `1`: proposal validation failures exist. COMMANDER records the failures and
  continues to Phase A finalization with KB apply skipped or partially applied.
- `2`: system error, such as unreadable run directory or parser failure in the
  validation engine. COMMANDER records `kb_validation_status: degraded` and
  continues without treating KB as authoritative for this run.

### `echelon kb apply`

Proposed interface:

```bash
echelon kb apply --run-id <run-id>
```

Responsibilities:

1. Run validation first.
2. Snapshot canonical KB checksums before mutation.
3. Apply accepted proposals through deterministic writers.
4. Deduplicate against existing entries.
5. Preserve append-only invariants.
6. Validate canonical KB files after mutation.
7. Write `runs/<run-id>/kb-apply-report.yaml`.
8. Update usage/application metrics.

`apply` is the only Phase A writer to canonical KB files.

## Apply Outcomes

Each proposal receives exactly one outcome:

- `accepted`: proposal created or updated a canonical KB entry.
- `rejected`: malformed, unsafe, unsupported, missing evidence, or bad
  provenance.
- `skipped_duplicate`: already represented in canonical KB.
- `needs_review`: semantically plausible but conflicts with existing KB, attempts
  promotion/demotion, or requires human policy.
- `queued`: deterministic lock/contention prevented safe apply.

Rejected proposals do not block Phase A finalization. They are visible in the
apply report.

Systemic apply failures still do not block the user-requested run. They disable
KB mutation for the run, mark the KB step degraded, and require a report entry:

- proposal directory cannot be read
- unsupported apply-engine schema version
- canonical KB is unparseable and recovery fails
- canonical KB post-apply validation fails
- direct canonical KB mutation is detected outside `echelon kb apply`

In all of these cases, Phase A continues. Canonical KB files are left unchanged
or restored to the pre-apply snapshot, `kb-apply-report.yaml` records the failure
when possible, and final output warns that durable learning was not applied.

## Deduplication and Normalization

The apply engine normalizes proposal payloads before comparison:

- trim insignificant whitespace
- normalize case for names and tags where appropriate
- compute stable semantic fingerprints from type, normalized name, target, domain,
  tags, and evidence refs
- compute project fingerprint deterministically from `git remote get-url origin`
  when `project_fingerprint: auto`
- add provenance fields required by `knowledge-base/kb-schema.md`

Duplicate detection is deterministic and conservative:

- exact proposal ID already applied: `skipped_duplicate`
- exact semantic fingerprint already present: `skipped_duplicate`
- near match with conflicting description or lower confidence: `needs_review`

The harness must not use an LLM for deduplication in this pass.

## Direct-Write Detection

At Phase A init and before finalize, the harness records checksums for canonical
KB files:

```text
knowledge-base/calibration-profile.yaml
knowledge-base/estimates-log.yaml
knowledge-base/patterns.yaml
knowledge-base/pitfalls.yaml
knowledge-base/agent-scores.yaml
knowledge-base/internalization-log.yaml
knowledge-base/evolution-signals.yaml
knowledge-base/sage-decisions.yaml
```

If a canonical KB file changes and no `echelon kb apply` report accounts for the
change, finalize reports a contract violation. In the first migration stage this
is a warning. Once Phase A agents are converted, it remains non-blocking for the
product run but is upgraded to a high-severity KB contract violation in the final
report and any maintainer-facing health report. The remedy is to fix the KB
writer, not to stop the user's spec run.

## Phase A Workflow Integration

During FINALIZE:

1. REALIST, MIRROR, ADAPTIVE, INTERNALIZER, AUDITOR, CONSOLIDATOR, SCOREKEEPER,
   SAGE, and VETERAN produce proposal artifacts when they have durable learning.
2. COMMANDER runs `echelon kb validate --run-id <run-id>`.
3. COMMANDER runs `echelon kb apply --run-id <run-id>`.
4. COMMANDER includes `kb-apply-report.yaml` in final artifacts.
5. `finalize-run.sh` stages `knowledge-base/`, `runs/<run-id>/kb-apply-report.yaml`,
   and any published proposal/report artifacts selected for Phase A provenance.

Phase A finalization attempts to include the apply report, but the absence or
failure of the apply report does not stop finalization. COMMANDER records
`kb_apply_status: missing`, `failed`, or `degraded` in state and in the final
summary. The run continues with durable learning skipped for this iteration.

## Usage Measurement

At init and context-pack assembly, the harness writes:

```text
runs/<run-id>/kb-usage.yaml
```

The usage record includes:

- KB entry ID
- source KB file
- agent receiving the entry
- phase receiving the entry
- selection reason: `global`, `same_project`, `language_rule`, `calibration`,
  `recent_sage_decision`, or `manual_context`
- whether the agent cited or referenced the entry in an output artifact or
  `echelon_result`
- downstream result when known

The first pass may compute citation/reference use with deterministic string and
ID matching only. Later work may add semantic usage interpretation as a proposal
type, but deterministic evidence remains authoritative.

## Benefit Metrics

`kb-apply-report.yaml` includes per-run metrics:

- `proposal_count`
- `accepted_count`
- `rejected_count`
- `skipped_duplicate_count`
- `needs_review_count`
- `queued_count`
- `acceptance_rate`
- `duplicate_rate`
- `schema_health_before`
- `schema_health_after`
- `stale_or_invalid_entries_found`

`kb-usage.yaml` enables cross-run metrics:

- `reuse_rate`: loaded entries that were cited or acted on
- `pattern_outcome_rate`: patterns later validated or contradicted by feedback
- `sage_false_positive_rate`: overturned SAGE decisions over recent history
- `calibration_delta`: estimate correction trend over runs
- `proposal_acceptance_trend`: accepted proposals over submitted proposals
- `staleness_rate`: stale or invalid entries over scanned entries

LLMs may explain why knowledge helped. The harness records whether it was loaded,
cited, applied, rejected, contradicted, or validated.

## Legacy Migration

Existing KB files remain canonical. The first implementation separates legacy debt
from new proposal quality:

1. Add a deterministic KB health report that validates current files.
2. Mark legacy schema violations in the health report instead of failing all new
   proposals immediately.
3. Ensure newly applied proposal entries satisfy the current schema.
4. Add targeted migration commands for legacy entries with missing timestamps,
   missing run IDs, or missing project fingerprints.
5. After migration, make full canonical KB validation authoritative for deciding
   whether KB mutation occurs, but still non-blocking for the Phase A run itself.

This lets the proposal pipeline land without forcing an immediate rewrite of all
historical memory.

## Safety and Recovery

The apply engine uses existing KB recovery concepts where possible:

- parse canonical files before apply
- write temporary files and atomic replacements
- preserve append-only files
- use KB locks around canonical mutation
- leave queued work when lock acquisition times out
- never delete historical entries without explicit archive/migration policy
- write a report even when apply fails after partial validation

If post-apply validation fails, the engine restores the pre-apply snapshot and
marks the run report as failed. The Phase A run then continues with KB mutation
disabled for that run.

## Testing

Unit tests:

- common proposal envelope validation
- type-specific payload validation
- target/type compatibility
- project fingerprint auto-fill
- duplicate detection
- direct-write checksum detection
- apply report metrics

Integration tests:

- fake Phase A run with valid proposals applies to canonical KB
- malformed SAGE proposal is rejected and `sage-decisions.yaml` remains parseable
- duplicate pattern proposal is skipped
- canonical KB parse failure skips apply, writes a degraded report, and the run
  continues
- lock timeout queues proposals without data loss
- failed usage recording records degraded status and the run continues

Contract tests:

- Phase A learning agent prompts reference proposal templates
- Phase A learning agent prompts do not instruct direct canonical KB writes
- FINALIZE phase attempts `echelon kb validate` and `echelon kb apply` but
  continues on KB degradation
- `finalize-run.sh` stages the KB apply report when present

## Rollout Plan

1. Add proposal schemas, templates, validator, and tests.
2. Add `echelon kb validate` and `echelon kb apply` without changing agents.
3. Add KB health and direct-write checksum reporting in warning mode.
4. Convert SAGE decision recording to proposals first, because malformed YAML is
   already visible in the startup banner fallback path.
5. Convert MIRROR pattern/pitfall writes to proposals.
6. Convert AUDITOR and INTERNALIZER observations to proposals.
7. Attempt `kb-apply-report.yaml` generation in Phase A FINALIZE and record
   degraded status when absent.
8. Turn direct canonical KB mutation from warning into high-severity KB contract
   violation while keeping the product run non-blocking.

## Open Questions

- Should proposal artifacts be published under `specs/<id>/kb-proposals/`, or is
  `kb-apply-report.yaml` enough public provenance?
- Should `echelon_result` include proposal summaries in addition to proposal file
  paths?
- Which legacy KB violations should be auto-migrated, and which should remain
  explicit `legacy_untrusted` entries?
- Should global promotion remain a `needs_review` outcome until a separate
  cross-project storage implementation exists?
