# Phase: re-knowledge-discovery (internal; installed routing disabled)

Agent: `echelon.re-discoverer`. Mode: initial discovery before analysis publication.
Owner: the existing RE controller, using `DiscoveryController.step()` under its
run ownership lock. This phase is not a second scheduler.

## Context pack and dispatch

Supply only the committed `untrusted_discovery_context` bytes authenticated by
`DiscoveryAcquisition`, or a controller-authenticated
`untrusted_discovery_repair_context` containing that safe context, the prior
screened candidate as opaque UTF-8 text and one closed deterministic admission
reason. Opaque retention allows duplicate-field and otherwise invalid JSON to be
repaired without reparsing it as authority. The ordinary
context contains selected source/depth, originating obligation, screened inventory
and evidence, required source/domain categories, and recorded evidence outcomes.
Never supply a checkout path, raw inventory mapping or private receipt.
Schema-2 context includes the exact `category_depth_applicability` object generated
from the controller's canonical protocol-2.8 policy. Its `quick`, `standard` and
`deep` entries each contain `domain` and `source` objects with exact `required` and
`outside_requested_depth` category arrays. Select only the entry named by `depth`;
do not reconstruct a second matrix in prose or provider logic. Historical schema-1
contexts retain their original field set and canonical identity.

Freeze this phase contract together with the rendered neutral role as the
controller's `agent_bytes`. Freeze the provider/model/execution contract in the
run-wide account. Reserve before invoking the backend. It must not log unscreened
responses or allocate another budget. Fresh reviewed-analysis accounts may freeze
a positive producer-repair ceiling. Only a safely captured authorial admission
failure may consume one of those turns; storage, transport and authority failures
remain terminal. A repair call uses the same source, snapshot, acquisition revision,
role, provider, reservation and aggregate account, and asks for one complete
replacement payload. Historical accounts without that frozen field retain zero
repair turns.
The backend screens the complete response (including the transport envelope)
before returning authorial JSON bytes and normalized usage to the controller.

The opt-in `KnowledgeLLMBackend` uses Echelon's existing `AICodingCliProvider`
facade and its `run_constrained_prompt_result` operation, not a concrete Codex
backend. Normal configuration and environment overrides select the provider;
the bridge freezes the resolved execution configuration and provider/model.
Native transport, tool restrictions, screened capture and usage handling remain
behind the provider boundary. Unsupported required capabilities produce an
actionable pre-dispatch error, never silent provider substitution. Ordinary
provider execution and installed RE routing remain unchanged.

The current backend capability implementation is Codex; this does not change
the configured provider or imply that the other native adapters implement the
same safeguards. Their ordinary Echelon execution remains available. An adapter
without this optional capability cannot execute this new discovery path yet.

The `configured-provider-accounted` contract reserves before invocation and
charges observed usage afterward. Missing/untrusted usage consumes the conservative reservation
or a larger observed amount. An observed reservation breach blocks all further
dispatches on this account, including review and other sources. An in-flight
native invocation can overshoot: these are admission/accounting limits, not a
hard native token cutoff. The complete Echelon-rendered prompt is byte-bounded;
the native provider's internal framing is not included in that byte count.
Process timeouts cannot guarantee cancellation of remote spend. Never report exact wire-token
enforcement for this mode. Existing `offline-scripted` contract identities and
accounting remain unchanged.

Scripted-process tests can verify wiring, not native tool/storage isolation or
semantic quality. Those require separate validation before ordinary live routing.
The independent real-model evaluation and release gates still apply.
Pin the requested source selection independently of the full declared catalog.

## Authorial response contract

Return one UTF-8 JSON object, without extra fields. All evidence references are
IDs from the supplied context; selector offsets are original-file byte offsets.

For `kind: discovery_proposal`, also include:

- `schema_version: 2` and `source_id` exactly as supplied.

- `domains`: objects with `key`, `description`, `evidence_ids` (at most 256).
- `subjects`: objects with `key`, `target` (domain key or `source`), `description`,
  `category_ids`, and `evidence_ids` (at most 1,024). Each proposed domain needs
  an evidence-supported subject. `category_ids` must be nonempty and contain only
  the selected depth row's `required` categories for that target kind. Categories
  listed under `outside_requested_depth` never appear on a subject.
- `inventory`: exactly one object per inventory path: `path`, `owner` (subject key
  or null), `reason`. Unassigned paths remain visible for reconciliation.
- `obligations`: exactly one object for every supplied source category at `source`
  and every supplied domain category at each proposed domain. Each object has
  exactly `target`, `category`, `disposition`, `subject_keys`, `rationale`, and
  `evidence_ids`. Disposition is `analyze`, `not-applicable`, `unknown`, or
  `outside-requested-depth`. `subject_keys` is the exact sorted set of subjects at
  that target carrying the category. `analyze` requires at least one such subject
  and visible supporting evidence: its `evidence_ids` are a subset of the union of
  those subjects' evidence and intersect every listed subject's evidence.
  `not-applicable` requires visible scoped
  evidence, except that the authenticated wholly empty inventory is itself the
  scope evidence. `unknown` cites target-local supplied evidence (including an
  authenticated source-local withheld boundary), or uses an empty citation only
  for exact authenticated empty-source authority; it never means absence.
  `outside-requested-depth` is limited to the selected matrix complement and is
  forbidden for deep. Its evidence may be empty only for authenticated empty-source
  authority; nonempty-source rows keep the ordinary visible target-local rule.
- `questions`: `target`, `question`, `evidence_ids` objects (at most 256).

For `kind: evidence_requests`, use `schema_version: 1`, the exact supplied
`source_id`, and `requests` (1–16 objects), each with:

- `obligation_id`: the supplied originating obligation ID.
- `reason_class`: `missing-behavior`, `ownership` or `relationship`.
- `selector`: `source_id`, `path`, `byte_start`, `byte_end` (same selected source,
  snapshot-relative path, nonnegative bounded range).

The authorial response may be one bare JSON object with only trailing whitespace,
or that object followed by the exact minimal
`echelon_result: {verdict: DONE, state_updates: {}}` transport suffix specified by
the neutral role. Every other suffix is rejected. The optional envelope is not a
semantic approval. A backend returns only screened authorial JSON to admission;
no envelope fields become run state.
The normalized schema-2 proposal and its receipt are independently bounded at
262,144 bytes before any authorial capture or ordinary object is published; exactly
262,144 bytes is admissible and the next byte fails without persistence.

## Controller outputs and routing

The controller records reservation, safe capture and applied-result receipts.
`evidence_ready` means the batch is resolved and its context revision committed;
the next owner invocation may request another provider turn on the same account.
`proposal_ready` is a staged proposal requiring independent review, orphan
reconciliation and category assessment. It cannot publish an analysis plan.
`repair_ready` means the screened capture failed a closed authorial admission rule;
the next owner invocation may spend one frozen repair turn using the authenticated
repair context. The exact repair ceiling is enforced from durable account history,
so reopen never resets it and terminal `discovery-repair-limit` never invokes the
provider again.
The internal `DiscoveryReviewController.step()` may review that committed staged
proposal using a separate role/context and the same run-wide account. Review also
consumes the source-turn ceiling. Repeating discovery after this handoff returns
the staged producer result; it does not start another producer call or reset work.
`blocked` reports a fixed reason and retains charges/capture. Repeating an unknown
dispatch or a terminal invalid/no-progress response never invokes a provider again.

Provider/resource failures and incomplete artifacts are not acceptable debt.
Analysis, source and workspace synthesis/publication remain later workflow stages.
Schema-1 proposal and review objects remain readable historical records and retain
their canonical identities. They are not category-aware activation authority; this
phase never upgrades them or activates schema-2 planning.
