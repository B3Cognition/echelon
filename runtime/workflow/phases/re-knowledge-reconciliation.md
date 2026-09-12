# Phase: re-knowledge-reconciliation (internal; installed routing disabled)

Agent: `echelon.re-knowledge-reconciler`. Mode: producer or independent verifier,
chosen by the existing protocol-2.8 lifecycle for one frozen
`KnowledgeReconciliationWorkItemV1`. No new controller or nested scheduler.

## Context pack

The existing owner supplies only the canonical `reconciliation_context` bytes:
active work identity, reviewed category assessments, Safe snapshot evidence,
normalized accepted lower results, exact inherited debt (including the typed
`InheritedResidualDebtContextV1` view of accepted L3 debt) and authenticated evidence
request outcomes. Producer mode also receives durable reviewer feedback; verifier
mode receives the immutable candidate in a fresh context, without producer reasoning.
The trusted `response_authority` supplies the exact work/candidate identities,
complete obligation/result arrays, and per-check evidence grounding minimums; agents
copy these values and never reconstruct content hashes.
Carried L4 limitations include the exact original acceptance, debt items and candidates.
Never supply private evidence mappings, source checkout paths or transcripts.

## Execution and output

Reserve the producer/verifier pair through the existing L4ResourceStore using its
one-time authenticated account transfer. Revisions retain that account and the
existing finite attempt limits. Freeze the neutral role, phase and closed response
schema in the explicit workflow authorization; screen complete provider bytes before
ordinary persistence. Retain indeterminate producer charges; release only the
known never-started paired verifier through the existing resource machinery.

Producer writes exactly `knowledge-reconciliation-candidate.json` containing
`KnowledgeReconciliationCandidateV1`; verifier writes exactly
`knowledge-reconciliation-review.json` containing
`KnowledgeReconciliationReviewV1`. Both contain the exact seven checks enumerated by
the supplied schema/context. Persist reviewed failure and its fingerprint before
another permitted attempt. An unchanged outcome terminates without another call.
The explicit `DebtResolvingKnowledgeReconciliationCandidateV1` and
`DebtResolvingKnowledgeReconciliationReviewV1` subtypes carry separate closure
proposals and exact reviewed IDs. Accepted closure produces a
`ReviewedKnowledgeDebtClosureV1` bound to the original acceptance and captured review.

The existing sole-writer controller builds target roots after their slices and
source roots after all targets, only after deterministic validation and an
independently captured review. A run root binds the exact reviewed lower closure.
Only explicitly authorized, investigated unavailable/dynamic dependency ambiguity
may become `ReviewedKnowledgeDebtAcceptanceV1`; no other failure becomes debt.

## Routing contract

`echelon_result: {verdict: DONE, state_updates: {}}` reports transport completion
only. The agent cannot activate revisions, grant debt, write state, or mark a run
complete. This internal route is disabled for installed command dispatch. Scripted
tests do not certify native transport isolation or release readiness.
