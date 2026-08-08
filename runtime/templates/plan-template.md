# Implementation Plan: {feature_name}

**Feature**: `{spec_id}-{feature_slug}`
**Architect**: ARCHITECT (phase3-how)
**Date**: {date}
**Stack**: {primary_stack}

---

## Plan Section Contract

Every `plan.md` must include these H2 sections:

1. Summary
2. Technical Context
3. Architecture Decisions
4. Requirement Preservation
5. Project Structure
6. Implementation Phases
7. Testing Strategy
8. Risks
9. Constitution Check

Domain-specific sections may be added after the required sections. Keep detailed ADR
rationale in `research.md` when it would make this plan hard to scan.

---

## Summary

State the deliverable, target users, main implementation approach, and the work that
must not be silently deferred.

## Technical Context

### Stack

| Layer | Technology | Reason |
| --- | --- | --- |
| {layer} | {technology} | {reason} |

### Dependencies

| Dependency | Purpose | Constraint |
| --- | --- | --- |
| {dependency} | {purpose} | {constraint} |

### Storage

List data stores, generated artifacts, persisted state, external services, and
read-only sources.

### Platform

State runtime platforms, toolchains, device/browser/server constraints, and any
version floors.

### Constraints

List non-negotiable architecture constraints from `spec.md`, `constitution.md`,
and validated assumptions.

## Architecture Decisions

Record concise ADR summaries here. Each row should point to detailed rationale in
`research.md` when the rationale is longer than a few sentences.

| ADR | Decision | Alternatives Rejected | Evidence |
| --- | --- | --- | --- |
| ADR-001 | {decision} | {alternatives} | {source/grade} |

## Requirement Preservation

For every MVP requirement whose behavior can be changed by architecture, record the
product invariant from validated `spec.md`, the implementation mechanism, and the
evidence that the mechanism preserves the invariant. HOW may refine implementation
mechanisms, but it must not reinterpret product behavior. If a mechanism changes a
product invariant, mark `Preserves?` as `no` or `escalated` and route back to WHAT
or the user for a spec amendment before planning continues.

| Requirement | Product Invariant | Architecture Decision | Preserves? | Evidence |
| --- | --- | --- | --- | --- |
| FR-001 | {observable behavior that must remain true} | {mechanism or ADR} | {yes/no/escalated} | {why this preserves the invariant} |

## Project Structure

```text
{project-root}/
├── {path}/
└── {path}/
```

For each important directory or module, state its responsibility and what it must
not own.

## Implementation Phases

Each phase should have a clear goal, owner, ordered work, and exit criteria.

### Phase 1: {phase_name}

**Goal:** {goal}
**Owner:** {agent_or_role}

**Work:**
- {work_item}

**Exit Criteria:**
- {check}

## Testing Strategy

| Scope | Tool/Method | Pass Condition |
| --- | --- | --- |
| Unit | {tool} | {condition} |
| Integration | {tool} | {condition} |
| E2E/Manual | {tool_or_process} | {condition} |

Include explicit handling for deferred or manually-gated verification.

## Risks

| Risk | Impact | Mitigation | Owner |
| --- | --- | --- | --- |
| {risk} | {impact} | {mitigation} | {owner} |

## Constitution Check

| Principle | Compliance |
| --- | --- |
| {principle} | {how_plan_complies} |
