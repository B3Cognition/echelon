# Banzai Default Resolution Design

## Goal

Let Banzai resolve a bounded product-design ambiguity when the normal
human-input route has no evidence-backed recommendation, while retaining a
durable audit trail and failing closed outside that narrow authority.

## Problem

`human_clarification_required` currently has only two outcomes: an
evidence-backed recommendation can be replayed, otherwise the run waits for a
human. This conflates a user-owned fact or authorization with a normal product
calibration decision, such as choosing one interaction-radius contract from a
small set of internally consistent choices.

The provider must not be able to mark its own choice as autonomous. SAGE is a
critic and CARTOGRAPHER is prohibited from inventing a missing value, so neither
agent should be granted that authority directly.

## Authority model

The harness owns eligibility. A provider may supply only a typed candidate
envelope; it cannot mark a decision automatic or choose its answer.

The initial `banzai_default` capability is limited to an ordinary Banzai
product default. It is eligible only when all of the following hold:

- Banzai mode is active.
- The source is a `phase1-why2` provider escalation with
  `human_clarification_required`, material classification, free-text answer,
  and no existing recommendation.
- SAGE supplied exactly one structurally valid default candidate tied to the
  same escalation question and one unresolved issue.
- The candidate is a bounded product calibration. It identifies affected
  requirements, at least two alternatives, constraints, and source artifact
  references. It does not claim an unavailable external fact.
- The candidate is neither external-prerequisite nor high/critical risk.
- The fingerprint has not already received a default in this run.

Anything outside those checks remains awaiting-human. A malformed candidate,
COMMANDER failure, or a failed repair also remains fail-closed; no alternative
is silently tried.

## Flow

```text
SAGE WHY2 STOP_AND_ASK + default-candidate envelope
  -> harness validates candidate and seals a pending Banzai decision
  -> COMMANDER chooses one exact free-text answer from registered context
  -> harness records immutable resolution and an autonomous-default ledger
  -> clarification handler records the receipt and sends CARTOGRAPHER to WHAT
  -> Understanding and WHY2 revalidate the revised requirements
```

The existing direct Banzai path for a provider's evidence-backed recommendation
is unchanged. This route is exclusively the missing-recommendation case.

## Durable state and audit

The sealed decision remains the canonical authority. A new
`autonomous_default_ledger` state entry records the decision ID, candidate
fingerprint, question, selected answer, selected-by `COMMANDER`, source phase,
policy capability, and declared source references. The normal clarification
receipt retains the exact question and answer for CARTOGRAPHER's context. The
candidate fingerprint canonically covers those references; it is not a claim
that the provider independently hashed project artifacts.

The state store must reject a second resolution for the same candidate
fingerprint. A resolution remains tied to the original state revision and
cannot be substituted by a generic state write.

## Future elevated authority

The candidate and ledger use an explicit `authority_capability` field. This
first implementation recognizes only `banzai_default` and never accepts an
elevated capability. A later `super-banzai` authority profile can add named,
owner-granted capabilities (for example `policy_authoring`,
`external_assumption`, or `irreversible_scope`) without changing the evidence,
decision, or audit shape. It must be scoped and supplied by the run owner; it
must never be inferred from provider output.

## Verification

- A valid missing-recommendation candidate becomes one COMMANDER resolution in
  Banzai and routes to WHAT.
- The selected answer and candidate fingerprint are durable and exact.
- The same decision cannot consume a second automatic attempt.
- Missing/malformed candidates, external prerequisites, high/critical risks,
  non-Banzai modes, and an absent authority capability stay awaiting-human.
- Existing recommended-answer and proportional-quality paths retain their
  current behavior.
