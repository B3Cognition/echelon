# Phase: re-knowledge-discovery-review (internal; installed routing disabled)

Agent: `echelon.re-discovery-reviewer`. Mode: independent discovery review before
analysis-plan activation. Admission: `DiscoveryReviewBoundary`. The existing RE
owner invokes `DiscoveryReviewController.step()` under its run ownership lock;
the operation is not a second scheduler.

## Context pack and execution owner

The existing RE controller supplies only the bytes returned by
`DiscoveryReviewBoundary.provider_bytes(binding_id, proposal_receipt_id)`: the
authenticated screened discovery context, normalized candidate and deterministic
review obligations. Do not supply producer conversations, reasoning transcripts,
private evidence mappings, local paths or earlier reviewer verdicts.

Use a fresh independent reviewer invocation. Bind the rendered neutral role and
this phase contract, provider/model, candidate, context and response in the same
logical-run resource account used by discovery. Reserve before dispatch, persist
the screened capture before applying it, and retain unsettled charges on restart.
Do not create a review-local budget or nested result-repair loop.

The internal operation accepts only a ledger-committed producer proposal and
uses the producer's existing account. Discovery and review share token, active
time and source-turn ceilings. A review is a separate reserved call with its own
frozen role/phase and context identities; it never runs the producer implicitly.
The existing capture and application records preserve the exact result and
feedback. Reopening cannot change provider, role, reservation or proposal.

Installed review dispatch remains disabled. The current backend contract permits
only `offline-scripted` execution; a recorded scripted call does not certify
independent real-model review. Passive admission receipts retain
`execution_certification_required: true` and `analysis_certified: false`.
Neither path can activate a plan, grant debt acceptance or mark analysis complete.
Production transport isolation, pre-log screening, bounded execution and actual
independent-invocation certification remain required before live routing.
The Codex adapter's opt-in `run_prompt_screened` supports bounded, non-streaming
Echelon-side response screening with the existing RE quarantine callback. It does
not certify native Codex logs/storage, tools-free execution, complete-wire token
bounds or invocation independence, and is not wired into this offline operation.

## Authorial response

Return one UTF-8 JSON object with exactly these fields:

```json
{"schema_version":1,"kind":"discovery_review","proposal_id":"sha256:...","verdict":"ready","domains":[],"subjects":[],"inventory":[],"overlaps":[],"findings":[]}
```

Copy the context's `candidate_id` into `proposal_id`. Verdict is `ready` or `revise`.

- `domains` and `subjects`: every candidate key exactly once, with
  `{key, verdict, rationale, evidence_ids}`. Verdict is `supported` or `revise`.
  Support needs visible supplied evidence including the candidate row's own
  evidence. Revision may cite withheld evidence or an explicit missing-evidence
  rationale. No invented or private evidence IDs.
- `inventory`: every path exactly once, with
  `{path, owner, disposition, rationale, evidence_ids}`. Preserve the candidate
  owner verbatim, including null. The reviewer cannot edit assignments.
  `owned` needs visible same-path evidence also proposed for that owner.
  `non-behavioral` needs a null owner and fully visible whole-file evidence;
  it is a semantic judgment, not an inference from missing excerpts.
  `excluded` needs a null owner and a deterministic empty/nonregular/opaque or
  policy-excluded inventory disposition. Ordinary partial redaction is not whole
  file exclusion. `unknown` and `needs-assignment` require revision.
- `overlaps`: each pair enumerated in the supplied `overlap_pairs` exactly once, with
  `{subject_keys:[a,b], disposition, rationale, evidence_ids}`. Dispositions are
  `shared-evidence`, `distinct` or `conflict`. The first two need visible evidence
  from both subjects on their common path; conflict requires revision. Either
  subject order is accepted and normalized; reversed duplicates are duplicates.
- `findings`: `{target, reason_class, rationale, evidence_ids}`. Target is `source`
  or a candidate domain key. Reason class is `missing-behavior`,
  `unsupported-domain`, `ownership`, `overlap` or `evidence-gap`. Revision requires
  at least one actionable finding. Ready requires no findings or unresolved rows.

Rationales must be nonempty and bounded by the supplied admission contract.
Evidence IDs always reference the screened context. Do not return category
verdicts, debt acceptance, edited candidates, budget settings or state updates.
Follow the JSON with the role's minimal `echelon_result` envelope. The future
backend must screen the entire response before extracting authorial JSON; no
unscreened response may enter ordinary logs, artifacts or error messages.

## Admission outputs

Context preparation rejects more than 4,096 overlap pairs with
`discovery-review-overlap-bound` before provider work, and rejects an oversized
context without truncation. Admission bounds both the normalized review and its
receipt before ordinary persistence so every admitted result can be replayed.

`ready_for_planning` means structurally admitted reviewer output only.
`revision_required` retains normalized findings for the next authorized producer
attempt. Both require independent execution certification; neither certifies
analysis. The controller must also ensure the candidate is the active committed
revision before activation. Repeated terminal output cannot reset attempts,
expand scope or allocate resources. A malformed review or unavailable local
authority remains a failure, not accepted uncertainty.

The operation returns `review_ready` or `revision_required` with that exact passive
receipt, or `blocked` with a closed reason. Repeating a completed/terminal step
returns its stored result without a call. An uncaptured reserved dispatch is
indeterminate and retains its full charge; do not automatically repeat it.
A captured but unapplied response is recovered by admission only, without another
provider call. A local storage failure preserves this recovery opportunity instead
of converting it to model rejection. Revision findings remain available through
`read_review`; this increment does not launch producer repair or reset counters.
