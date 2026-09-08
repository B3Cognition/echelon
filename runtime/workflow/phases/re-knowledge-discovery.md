# Phase: re-knowledge-discovery (internal; installed routing disabled)

Agent: `echelon.re-discoverer`. Mode: initial discovery before analysis publication.
Owner: the existing RE controller, using `DiscoveryController.step()` under its
run ownership lock. This phase is not a second scheduler.

## Context pack and dispatch

Supply only the committed `untrusted_discovery_context` bytes authenticated by
`DiscoveryAcquisition`: selected source/depth, originating obligation, screened
inventory and evidence, required source/domain categories, and recorded evidence
outcomes. Never supply a checkout path, raw inventory mapping or private receipt.

Freeze this phase contract together with the rendered neutral role as the
controller's `agent_bytes`. Freeze the provider/model/execution contract in the
run-wide account. Reserve before invoking a bounded, tools-free backend. Its full
request, including transport wrappers, must fit the input reservation. It must not
log unscreened responses, perform result-repair calls or allocate another budget.
The backend screens the complete response (including the transport envelope)
before returning authorial JSON bytes and normalized usage to the controller.

The production backend is not enabled by this increment. Offline scripted backends
exercise the controller seam; proving production tool isolation, ceilings and
pre-log screening is still required before live routing.
The current stored contract accepts only `offline-scripted` execution and
`utf8-byte-upper-bound` input accounting. The controller's byte check is a necessary
lower bound, not validation of an exact-token or fully framed production request.
Pin the requested source selection independently of the full declared catalog.

## Authorial response contract

Return one UTF-8 JSON object, without extra fields. All evidence references are
IDs from the supplied context; selector offsets are original-file byte offsets.

Common fields: `schema_version: 1`, `source_id` exactly as supplied, and `kind`.

For `kind: discovery_proposal`, also include:

- `domains`: objects with `key`, `description`, `evidence_ids` (at most 256).
- `subjects`: objects with `key`, `target` (domain key or `source`), `description`,
  `evidence_ids` (at most 1,024). Each proposed domain needs a subject.
- `inventory`: exactly one object per inventory path: `path`, `owner` (subject key
  or null), `reason`. Unassigned paths remain visible for reconciliation.
- `obligations`: `target`, `category` objects: all supplied source categories for
  `source` and all supplied domain categories for each domain. No verdict fields.
- `questions`: `target`, `question`, `evidence_ids` objects (at most 256).

For `kind: evidence_requests`, also include `requests` (1–16 objects), each with:

- `obligation_id`: the supplied originating obligation ID.
- `reason_class`: `missing-behavior`, `ownership` or `relationship`.
- `selector`: `source_id`, `path`, `byte_start`, `byte_end` (same selected source,
  snapshot-relative path, nonnegative bounded range).

The transport ends with `echelon_result: {verdict: DONE, state_updates: {}}` as
specified by the neutral role. This is not a semantic approval. A backend returns
only screened authorial JSON to admission; no envelope fields become run state.

## Controller outputs and routing

The controller records reservation, safe capture and applied-result receipts.
`evidence_ready` means the batch is resolved and its context revision committed;
the next owner invocation may request another provider turn on the same account.
`proposal_ready` is a staged proposal requiring independent review, orphan
reconciliation and category assessment. It cannot publish an analysis plan.
The internal `DiscoveryReviewController.step()` may review that committed staged
proposal using a separate role/context and the same run-wide account. Review also
consumes the source-turn ceiling. Repeating discovery after this handoff returns
the staged producer result; it does not start another producer call or reset work.
`blocked` reports a fixed reason and retains charges/capture. Repeating an unknown
dispatch or a terminal invalid/no-progress response never invokes a provider again.

Provider/resource failures and incomplete artifacts are not acceptable debt.
Analysis, source and workspace synthesis/publication remain later workflow stages.
