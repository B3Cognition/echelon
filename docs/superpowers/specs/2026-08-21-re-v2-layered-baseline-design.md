# RE v2 Layered Baseline Design

**Date:** 2026-08-21  
**Finding:** EGR-165  
**Status:** Revised after protocol-boundary architecture review; implementation pending

> **Protocol note (2026-08-23):** This document remains the immutable design
> authority for protocol 2.2 and its API-only compact-baseline executor. The
> provider-eligibility and universal no-tools rules are superseded for newly
> created RE v2 runs by protocol 2.3 in
> `2026-08-23-re-v2-provider-neutral-execution-design.md`. Existing protocol-2.2
> runs retain the rules below unchanged.

## Purpose

EGR-165 turns the pinned RE v2 execution kernel into a useful layered system.
It adds a bounded, controller-certified run-local L1 compact baseline above
deterministic L0 inventory without introducing the expensive semantic-audit,
repair, or workspace-synthesis loops that remain assigned to later findings.

The completed increment must prove the architectural property that motivated
EGR-165: changing a higher-detail content policy adds or replaces only the
affected higher-layer artifact. It must not make accepted lower-layer bytes
stale merely because execution limits, provider choice, model choice, or a
different depth policy changed.

An accepted L1 result is useful on its own, but it is not a full-quality or
exhaustive reverse-engineering outcome. The operator-facing state is **L1
COMPACT BASELINE COMPLETE**, with semantic audit and workspace synthesis
explicitly reported as not run.

## Scope

This increment includes:

- protocol 2.2 scoped artifact and work-template identity;
- deterministic immutable workspace, source, and domain partition inputs;
- a production L0+L1 artifact dependency graph;
- deterministic, provider-neutral, size-bounded source and domain evidence
  packs with exact byte-level schemas;
- a bounded `echelon.re-baseliner` agent contract;
- deterministic structural and source-evidence certification;
- controller-generated per-source baseline roots;
- immutable run-local L1 materialization;
- durable per-work-item failure isolation, recovery, status, and final-banner
  support; and
- backward-compatible continuation of protocol 2.0 and 2.1 runs.

This increment excludes:

- cross-run or v1 artifact adoption, owned by EGR-166;
- semantic audit epochs and semantic repair, owned by EGR-167;
- workspace synthesis and workspace `re/` publication, owned by EGR-168;
- selective source/domain deepening, owned by EGR-169; and
- atomic element repair, owned by EGR-170.

## Architectural Choice

L1 uses a domain-first bounded DAG. Each provider dispatch owns exactly one
source or source-domain artifact and receives one controller-built context
bundle with a hard input ceiling. A deterministic controller step assembles an
accepted source root from exact accepted hashes.

This is preferred over a source-wide deep-analysis dispatch because failure and
reuse remain domain-local. The one source-level overview call consumes only the
bounded source pack and bounded domain projections. The DAG is preferred over a
two-pass analyzer/specifier flow because L1 is intentionally compact and must
not reproduce v1's repeated whole-domain generation cost before stable audit
epochs exist.

## Immutable Protocol Boundary

New layered runs use engine protocol `2.2`. Existing protocol `2.0` and `2.1`
runs keep their current immutable manifests, identity schema, deterministic L0
graph, and continuation behavior. Echelon never migrates or reinterprets their
receipts in place.

Protocol 2.2 uses run-manifest schema 2 because it adds partition-input,
artifact-policy-catalog, and executor-contract-catalog authority. Protocol 2.0
and 2.1 retain run-manifest schema 1. Loading dispatches on the exact supported
schema/protocol pair; schema 1 canonical bytes are never decoded and re-emitted
as schema 2. The ledger record envelope remains version 1, while nested scoped
artifact keys carry `identity_schema_version: 2`. Recovery selects event-payload
and execution-observation validators from the immutable engine protocol before
replay, so protocol-2.2 reservation/retry fields are neither inferred into nor
accepted from protocol-2.0/2.1 histories.

The schema-2 manifest is a closed canonical object. It does not retain the
schema-1 open `provider_contract` or `artifact_policy_versions` maps; their
protocol-2.2 replacements are immutable catalog references:

```text
CatalogReferenceV1 = {
  object_hash: string,
  relative_path: string
}

BudgetPolicyV2 = {
  token_limit: positive integer | null,
  active_ms_limit: positive integer | null,
  provider_attempt_limit: nonnegative integer,
  artifact_generation_attempt_limit: nonnegative integer,
  semantic_repair_round_limit: nonnegative integer,
  result_contract_retry_limit: nonnegative integer,
  shared_retry_limit: nonnegative integer,
  artifact_contract_retry_limit: nonnegative integer
}

RunManifestV2 = {
  schema_version: 2,
  engine: "re-v2",
  engine_protocol_version: "2.2",
  run_id: string,
  created_at: RFC3339 timestamp,
  source_snapshot_id: string,
  source_snapshot_kind: "workspace-git-composite",
  partition_manifest_id: string,
  workspace_partition_catalog: CatalogReferenceV1,
  artifact_policy_catalog: CatalogReferenceV1,
  executor_contract_catalog: CatalogReferenceV1,
  requested_goals: ["baseline"] | ["inventory"],
  initial_budget_policy: BudgetPolicyV2,
  parent_run_id: null
}
```

Each catalog reference resolves below `v2/inputs/`, uses one normalized safe
run-relative path, and names the digest of the exact canonical bytes at that
path. Paths may not be absolute, escape `v2/inputs/`, traverse a symlink, or
alias one another. The workspace-partition and artifact-policy catalogs use
`schema_version: 1`; the executor-contract catalog uses
`schema_version: 1`. Catalog schemas reject any other version. The manifest
hash covers all three references, the complete budget policy, and the existing
composite-snapshot and partition-manifest identities. `parent_run_id` is
literally null because EGR-165 performs no cross-run adoption; EGR-166 must
introduce a new compatible manifest contract before it can authorize lineage.

For a baseline goal, the budget-policy attempt limits are `2`, `2`, `0`, `1`,
`1`, and `1` respectively in the field order above. For an inventory goal they
are `0`, `1`, `0`, `0`, `0`, and `0`: deterministic initial generation consumes
one generation attempt but no provider attempt or retry. Protocol-2.2 budget
projection consults the WorkItem's executor mode before incrementing provider
attempts; every initial or retry execution increments generation attempts, and
only provider-backed executions increment provider attempts. Token and active-
time authorizations may be null only when the operator deliberately creates an
unbounded run authorization; per-dispatch executor ceilings remain mandatory
and cannot be disabled by null run-wide authorization. Creation rejects any
manifest budget inconsistent with the selected goal before publishing it.

Protocol 2.2 continues to require the protocol 2.1 clean-Git composite source
snapshot. Before writing the run manifest, Echelon also runs the existing
deterministic domain-discovery rules against each source inside that snapshot.
It writes a canonical workspace partition catalog containing every source ID,
source path, presentation domain ID, stable domain key, domain root, file count,
line count, partition algorithm version, and source snapshot ID. Its hash
remains a run-level recovery input; it is not copied into every artifact key.

The catalog also contains independently hashed descriptors:

- `source_content_id`: the selection-policy version and complete source-root-
  relative file path/mode/content-hash set; declared workspace location is not
  content identity;
- `source_partition_id`: the full digest of the source ID, exact partitioner and
  ownership protocols, sorted source-level supporting-path set, and sorted
  partition-only domain descriptors containing stable domain key, presentation
  ID, root, `domain_partition_id`, and tagged owned/supporting path sets; it
  excludes file content hashes, content IDs, byte counts, and line counts;
- `domain_key`: the full lowercase `sha256:<64-hex>` digest of the existing v2
  canonical serialization of source ID, canonical domain root, and ownership-
  policy version, independent of sequential presentation numbering and sibling
  insertion; no truncated digest is authoritative identity;
- `domain_content_id`: the full digest of the ownership-policy version, stable
  domain key, sorted domain-root-relative path/mode/content-hash records for
  owned files, and separately tagged source-root-relative path/mode/content-hash
  records for explicitly enumerated source-level supporting files; and
- `domain_partition_id`: the exact partitioner and ownership protocols, stable
  domain key, canonical root, and the corresponding tagged owned/supporting path
  sets in those coordinate systems, excluding file content hashes.

Changing a sibling source does not change these IDs. Changing one domain does
not change another domain's IDs unless a deliberately shared supporting
artifact in that domain's declared read set also changed.

The workspace catalog and its descriptors are immutable run inputs rather than
provider output. This allows the complete graph to be constructed and pinned
before any provider dispatch. L0 partition and inventory artifacts materialize
and certify those exact inputs; they do not discover a second partition.

Run creation creates the unique `v2/` directory with no-clobber semantics,
writes and fsyncs all three canonical catalogs under `v2/inputs/`, and fsyncs
every content-addressed agent-contract and response-schema object they reference.
It then publishes the schema-2 manifest last using the existing no-clobber hard-
link commit marker. The active-run pointer is updated only after the manifest and
directory metadata are durable. A store without that final manifest remains
explicitly incomplete. Recovery rejects any missing, aliased, noncanonical,
unsafe, or hash-mismatched catalog/reference before replay or provider dispatch.

## Scoped Artifact Identity

Protocol 2.2 introduces an explicit scope value:

```text
ArtifactScope = {
  source_id,
  domain_key | null,
  content_id | null
}
```

`domain_key` is null for source-scoped artifacts and required for domain-scoped
artifacts. The human-facing sequential `domain_id` remains pinned descriptor
metadata but is not artifact identity. `content_id` is null for a partition-only
artifact and otherwise the corresponding `source_content_id` or
`domain_content_id`, so content-aware keys are affected only by files inside the
artifact's declared read set.

The protocol 2.2 artifact key is:

```text
ArtifactKey = {
  identity_schema_version,
  scope,
  partition_id | null,
  artifact_kind,
  layer,
  producer_protocol_version,
  layer_policy_hash,
  dependency_hashes
}
```

`partition_id` is null when an artifact does not depend on partition shape,
`source_partition_id` for source-scoped partition-aware artifacts, and
`domain_partition_id` for domain-scoped artifacts. The workspace-wide snapshot
and partition-catalog IDs remain manifest/recovery authority, but are excluded
from independently reusable scoped artifact keys.

Content-only edits therefore change `content_id` without changing partition
identity. Added, removed, or reassigned paths change the relevant partition ID.
The artifact-policy catalog declares whether each artifact kind requires or
forbids content and partition IDs; graph/model validation rejects every other
combination, so nullability cannot bypass identity inputs.

The same scope is part of `WorkTemplate` identity. Within one requested graph,
logical-output uniqueness is the tuple `(scope, artifact_kind, layer)`. The
graph resolves exactly one policy and therefore one `ArtifactKey` for each such
slot. Older objects produced under another policy may coexist in the
content-addressed store but are not competing outputs in the active graph. Two
domains may produce the same artifact kind without collision, and presentation-
ID renumbering does not stale unchanged domain artifacts.

`identity_schema_version` lets model decoding and canonical serialization
preserve the exact legacy representation of protocol 2.0/2.1 receipts while
using explicit scope for protocol 2.2. Legacy records gain no inferred fields
and therefore retain their existing identities and hash-chain validity.

Protocol 2.2 likewise uses closed work schemas rather than appending optional
fields to legacy work objects:

```text
WorkTemplateV2 = {
  identity_schema_version: 2,
  goal_id: "baseline" | "inventory",
  scope: ArtifactScope,
  artifact_kind: string,
  layer: "L0" | "L1",
  producer_id: string,
  producer_family: string,
  producer_protocol_version: string,
  layer_policy_hash: string,
  required_template_ids: [string, ...],
  executor_contract_hash: string,
  verifier_id: string,
  verifier_version: string,
  verifier_implementation_digest: string,
  result_contract_id: string,
  max_provider_attempts: nonnegative integer,
  max_generation_attempts: nonnegative integer,
  max_semantic_rounds: nonnegative integer,
  max_result_contract_retries: nonnegative integer,
  max_shared_retries: nonnegative integer,
  max_artifact_contract_retries: nonnegative integer
}

WorkItemV2 = {
  identity_schema_version: 2,
  template_id: string,
  goal_id: "baseline" | "inventory",
  output_key: ArtifactKey,
  required_artifact_hashes: [string, ...],
  producer_id: string,
  producer_family: string,
  producer_protocol_version: string,
  executor_contract_hash: string,
  verifier_id: string,
  verifier_version: string,
  verifier_implementation_digest: string,
  result_contract_id: string,
  max_provider_attempts: nonnegative integer,
  max_generation_attempts: nonnegative integer,
  max_semantic_rounds: nonnegative integer,
  max_result_contract_retries: nonnegative integer,
  max_shared_retries: nonnegative integer,
  max_artifact_contract_retries: nonnegative integer
}
```

Template IDs and work-item IDs are the digests of these complete canonical
objects. Required template IDs and artifact hashes are sorted and unique. A
WorkItem copies every producer, executor, verifier, result-contract, and attempt
field byte-for-byte from its template; its output scope, kind, layer, producer
protocol, policy hash, and dependency hashes must match the template slot and
resolved graph. `required_artifact_hashes` exactly equals the output key's
dependency hashes. The executor hash resolves to the one catalog entry whose
producer family matches the work object. No protocol-2.2 decoder accepts a
schema-1 `WorkTemplate` or `WorkItem` with inferred values.

`layer_policy_hash` is the full digest of the complete canonical artifact-policy
catalog entry, not a digest of a policy name or version label. The entry includes
the artifact kind, layer, content and evidence-pack policies, artifact schema,
required surfaces, canonicalization rules, context and output bounds, and every
other rule that can change accepted bytes. It therefore changes whenever the
content contract changes even if an operator mistakenly reuses a human-facing
version label. Extractor/producer protocol remains independently represented by
`producer_protocol_version`. Provider, model, run token ceiling, time ceiling,
and attempt authorization are execution controls and are deliberately absent
from artifact identity.

## Pinned Policy and Executor Catalogs

Protocol 2.2 replaces the single implicit layer-version assumption with a
canonical artifact-policy catalog. Each graph template resolves exactly one
catalog entry by layer and artifact kind. The catalog pins:

- content-policy version;
- artifact schema version;
- maximum canonical JSON and rendered Markdown sizes;
- maximum context-bundle bytes and conservative input-token estimates;
- required content sections;
- evidence and ownership rules; and
- producer protocol and result-contract versions.

The initial L1 policy is `compact-v1`. It is the only L1 content policy exposed
by EGR-165. Custom depth, source selection, and domain selection are deferred to
EGR-169.

The deterministic L0 selection policy is separately pinned as
`evidence-pack-v1`. It caps canonical source evidence packs at 48 KiB and domain
evidence packs at 96 KiB. Allocation uses only the policy's provider-neutral
`utf8-byte-upper-bound-v1` estimator: every canonical UTF-8 byte reserves one
conservative input token. Exact provider/model tokenizers never participate in
L0 selection and therefore cannot change evidence-pack bytes. They are used only
for execution preflight after a complete provider-request envelope exists and
may reject that request; they may not add, remove, reorder, or truncate evidence.

`evidence-pack-v1` is the only L0 evidence-selection artifact. An L1 content-
policy change does not rewrite or re-key it. A future higher layer that needs a
different selection derives a policy-specific context-selection artifact at
that higher layer directly from the accepted L0 inventory. It must not create a
second policy-specific L0 evidence pack. This preserves logical-output
uniqueness and the rule that deepening changes only the affected higher layer.

For a baseline goal, run creation resolves the L1 provider through the normal
workspace configuration cascade, including `.echelon/config.yml` `llm.cli` and
its provider-specific settings. Protocol 2.2 does not add a separate hidden
provider selector. Effective non-secret endpoint, API version/routing,
temperature, top-p, seed, reasoning, model, and completion settings must be
representable by the closed transport/executor/envelope schemas below; an
unsupported implicit default is an eligibility failure rather than mutable
runtime configuration. Resolution must succeed before the immutable manifest or
active-run pointer is written. An inventory-only diagnostic pins only its
selected deterministic executors and does not require an unused L1 provider;
continuation cannot later switch that immutable goal to baseline.

The manifest pins an executor-contract catalog by producer family:

- deterministic in-process execution for L0 source inventory, L0 source
  partition, L0 source/domain evidence packs, L1 context-bundle construction,
  and L1 source-root assembly; and
- the configured CLI or API provider adapter for L1 source and domain
  baselines.

The canonical executor catalog has exactly `schema_version: 1` and an array of
entries sorted by `producer_family`. Every entry has this exact shape, with no
extension fields:

```text
ExecutorContractEntry = {
  producer_family: string,
  execution_mode: "in_process" | "cli" | "api",
  provider_id: string | null,
  api_transport: ApiTransportAuthorityV1 | null,
  adapter_id: string,
  adapter_contract_version: string,
  executor_implementation_digest: string,
  producer_protocol_version: string,
  result_contract_id: string,
  model: {
    model_id: string,
    model_revision: string,
    revision_authority: "immutable_model_id" | "provider_resolved_revision",
    reasoning_effort: string | null
  } | null,
  request_renderer: {
    renderer_id: string,
    renderer_version: string,
    implementation_digest: string,
    agent_contract_hash: string,
    response_schemas: [{artifact_kind: "domain-baseline" | "source-overview",
                        schema_hash: string}, ...]
  } | null,
  request_tokenizer: {
    tokenizer_id: string,
    tokenizer_version: string,
    implementation_digest: string,
    fallback_estimator_id: "utf8-byte-upper-bound-v1",
    fixed_framing_byte_upper_bound: nonnegative integer
  } | null,
  reservation_calculator: {
    calculator_id: "bounded-dispatch-v1" | "bounded-in-process-v1",
    calculator_version: 1,
    implementation_digest: string
  },
  token_accounting: {
    normalization_id: string,
    normalization_version: string,
    implementation_digest: string,
    unknown_class_policy: "untrusted"
  },
  limits: {
    provider_context_tokens: positive integer | null,
    max_internal_calls: nonnegative integer,
    max_followup_input_tokens_per_call: nonnegative integer,
    max_completion_tokens_per_call: nonnegative integer,
    max_tool_rounds: nonnegative integer,
    max_tool_result_bytes_per_round: nonnegative integer,
    max_billable_tokens_per_dispatch: nonnegative integer,
    max_active_ms_per_dispatch: positive integer
  }
}

ApiTransportAuthorityV1 = {
  authority_schema: "api-transport-authority-v1",
  api_protocol_id: "openai-chat-completions",
  api_protocol_version: "1",
  base_url: string,
  request_path: string,
  non_secret_headers: [{name: string, value: string}, ...]
}
```

For deterministic in-process producers, `provider_id`, `model`,
`api_transport`, `request_renderer`, `request_tokenizer`, and
`provider_context_tokens` are null; internal-call, follow-up-input, completion,
tool, and billable-token limits are zero; and the calculator is
`bounded-in-process-v1`. API entries require non-null provider, transport,
model, renderer, tokenizer/estimator, and context-window values, positive
internal-call, completion-token, and billable-token limits, and
`bounded-dispatch-v1`. CLI entries require null API transport and remain
ineligible for compact L1 until a later closed CLI authority schema proves all
equivalent limits. A configured model alias is eligible only when the adapter
resolves it before manifest publication to either an immutable model ID or an
exact provider-reported revision that can be checked on every response. An
unresolved or unobservable revision makes the adapter ineligible. Every entry
requires a positive active-time limit.

The API base URL is canonicalized to a scheme, authority, and normalized path
prefix with no userinfo, query, or fragment. Production transport requires
HTTPS; loopback HTTP is permitted only by the conformance fixture. The request
path is normalized below that prefix. Header names are lowercase, entries are
sorted and unique by name, and authorization, cookie, proxy-authorization,
API-key, and any other credential-bearing headers are forbidden. Provider API
version, organization, project, region, or routing headers are included here
whenever they can affect request routing or model behavior. Credential values
and credential-source locations remain outside immutable authority and may
rotate without changing a run.

The full contract hash is the SHA-256 digest of this canonical entry; it is
stored by reference in every protocol-2.2 `WorkTemplate` and `WorkItem`. The
catalog itself is a strict canonical JSON object; entries, nested fields,
implementation digests, and nullability are schema-validated before the
manifest is committed.

Every executor, renderer, tokenizer, calculator, and normalizer implementation
digest is a full lowercase `sha256:<64-hex>` digest of the installed executable
or canonical module closure used for that registration. The agent-contract hash
uses the same tagged digest form over its exact canonical UTF-8 bytes. A version
label without the matching digest is not execution authority. Response-schema
entries are sorted and unique by artifact kind and contain exactly the domain-
baseline and source-overview authorial schemas for the L1 producer family. Each
schema is the deterministic strict-JSON-Schema projection of the matching pinned
artifact policy; creation and recovery regenerate it and require byte-identical
hash equality. A policy/schema mismatch makes the executor contract ineligible.

For L1, `bounded-dispatch-v1` computes the reservation rather than trusting a
number reported by the adapter. The controller first constructs the complete
immutable provider-request envelope defined below and computes
`initial_input_tokens` over every provider-visible input component—including
message framing, system and user content, strict response schema, and any
provider-defined reasoning/input framing—with the pinned exact tokenizer. When
exact tokenization is unavailable, the pinned one-byte/one-token upper bound is
applied to the complete canonical envelope plus the adapter contract's fixed
framing-byte upper bound. It then computes:

```text
billable_token_reservation =
    initial_input_tokens
  + max_internal_calls
      * max_completion_tokens_per_call
  + (max_internal_calls - 1)
      * max_followup_input_tokens_per_call
```

Preflight also requires
`initial_input_tokens + max_completion_tokens_per_call <=
provider_context_tokens` for the one-call adapter. The context-window check uses
the same exact-or-conservative input count as the reservation; it cannot rely on
a smaller adapter estimate.

The token-accounting normalizer defines disjoint billable input, visible-output,
cached-input, and hidden/reasoning classes. Cached input is classified within
the applicable input ceiling rather than double-counted. The provider's hard
completion ceiling must cover the sum of visible output and hidden/reasoning
tokens, so the reservation does not depend on whether a provider reports those
classes separately. Provider usage fields that the pinned normalizer cannot
classify make the observation untrusted. The adapter must enforce the internal-
call, aggregate-completion, tool-round, tool-result, context-window, and active-
time limits used by the formula. An adapter with an unbounded internal agent
loop, or one that cannot expose and honor these limits, is ineligible for
protocol 2.2 L1 execution.

EGR-165 includes one mandatory eligible implementation,
`bounded-api-baseline-v1`. It is a controller-owned, tool-free API transport that
performs exactly one provider request, permits no follow-up or tool call, applies
the provider's hard aggregate completion-token parameter, verifies the resolved
model revision on the response, and enforces the controller deadline. The
adapter requires exactly one non-refusal assistant content string and no tool
calls, extracts its UTF-8 bytes without Markdown-fence or prose repair, persists
those bytes as the provider-authored `baseline.json` candidate, and emits
transport result status only after that file is durably closed. Multiple choices,
non-string content, refusal, or tool-call content produces an empty captured
candidate inventory and an invalid raw result rather than heuristic extraction.
An endpoint without a hard aggregate completion cap or exact
revision authority cannot back this adapter. Existing agentic CLI adapters,
including the current general Codex and Claude CLI paths, remain ineligible
unless a future adapter version proves the same conformance contract. Run and
shadow creation must name the missing capability and fail before manifest or
active-pointer mutation; they may not silently weaken a hard limit. Shipping and
passing the live conformance fixture for `bounded-api-baseline-v1` is part of
EGR-165, not deferred integration work.

Its catalog entry uses `execution_mode: api`, `max_internal_calls: 1`, and zero
follow-up-input, tool-round, and tool-result limits. Its positive completion cap
is the exact provider parameter and its billable ceiling is at least the largest
legal provider-visible envelope input plus that cap, while remaining within the 262,144-token
per-dispatch safety ceiling below.

No `compact-v1` dispatch may reserve more than 262,144 billable tokens.
`max_billable_tokens_per_dispatch` is the executor-contract safety ceiling; the
item-specific value computed from the provider request must be less than or
equal to it. That computed value, not the catalog ceiling or an adapter-reported
estimate, is the reservation for the dispatch. The adapter must accept and
enforce exactly that value and may not lower or raise it at runtime. The
controller stores the exact canonical neutral baseliner agent contract as a
content-addressed object at run creation and pins its hash in the request-
renderer contract. It likewise stores the strict authorial response JSON Schema
and pins its hash. Credentials are never included; every other effective
provider setting that can affect routing, billed input, or generation is
canonicalized into the executor contract or request envelope rather than read
again at execution time.

The initial bounded API transport accepts exactly this request object:

```text
ProviderRequestEnvelopeV1 = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  executor_contract_hash: string,
  target_artifact_kind: "domain-baseline" | "source-overview",
  provider_id: string,
  model_id: string,
  model_revision: string,
  reasoning_effort: string | null,
  messages: [
    {role: "system", content_utf8: string},
    {role: "user", content_utf8: string}
  ],
  response_format: {
    kind: "json_schema",
    schema_name: "echelon_compact_baseline_v1",
    strict: true,
    schema_hash: string
  },
  generation: {
    temperature_micros: integer in [0, 2000000],
    top_p_micros: integer in [0, 1000000],
    seed: integer | null,
    max_completion_tokens: positive integer
  },
  tools: [],
  tool_choice: "none",
  stream: false
}
```

The two message entries are literal and ordered. Their complete contents—not a
prompt suffix or context hash—are provider-visible authority. The response
schema hash resolves to the exact object selected by the WorkItem artifact kind
from the renderer contract.
Target artifact kind byte-matches the WorkItem and selects the response schema.
Generation micros convert to exact decimal provider values by the adapter
contract; null seed means the field is omitted on the wire. Model, revision,
reasoning, completion cap, provider, schema hash, and executor hash byte-match
their pinned contracts. The adapter deterministically serializes the stored
envelope to its one API protocol and adds only the current credential header.
No environment setting, user CLI configuration, default system prompt, implicit
tool schema, or sampling default may add to or override the envelope.

Configuration resolution parses temperature and top-p as finite base-10 values
with at most six fractional digits and converts them exactly to micros; binary-
float rounding is not identity authority. Missing supported sampling values are
materialized as the adapter contract's explicit micros/seed literals before the
manifest is published. Out-of-range, over-precision, or unsupported provider
sampling options fail eligibility instead of being rounded or silently omitted.

Before every dispatch the controller persists the envelope as a content-
addressed object and then persists this exact canonical execution object:

```text
ExecutionInput = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  attempt_kind: "initial_generation" | "result_contract_retry" |
                "artifact_contract_retry",
  executor_contract_hash: string,
  agent_contract_hash: string | null,
  context_bundle_hash: string | null,
  provider_request_envelope_hash: string | null,
  deterministic_invocation: DeterministicInvocation | null
}

DeterministicInvocation = {
  schema_version: 1,
  producer_family: string,
  output_key: ArtifactKey,
  artifact_policy_hash: string,
  inputs: [{role: string, object_hash: string}, ...]
}
```

Provider-backed inputs require the agent, context, and complete envelope hashes
and a null deterministic invocation. The referenced envelope's embedded IDs and
contract values must match the ExecutionInput and WorkItem. Deterministic inputs
require a canonical closed invocation object and null agent, context, and
provider-envelope fields. Invocation inputs are sorted by role, roles are
unique, and each producer protocol defines its exact required role set; unknown
or missing roles are rejected. Exactly one branch is populated. The envelope is
fsynced before the ExecutionInput; the `execution_input_hash` is the object-store
hash of the latter bytes. Both are durable before `dispatch_started` records that
hash, the executor-contract hash, and computed token and active-time
reservations.

Immediately before a new `dispatch_started`, the controller loads the stored
envelope rather than re-rendering from the current installation. It independently
verifies the pinned renderer, agent-contract, response-schema, transport,
adapter, and tokenizer digests, reruns the calculator over the stored provider-
visible input, and requires byte-for-byte and integer equality. It appends and
fsyncs `dispatch_started` with the reservations, then—and only then—issues the
external request. Recovery may start a prepared dispatch only when no
`dispatch_started` exists for its ID. A durable `dispatch_started` means the
external call may already have been issued; recovery never issues that dispatch
ID again. Missing or corrupt execution-input or envelope authority fails closed
and never triggers a fresh provider call.

Provider, API transport/routing, executor implementation, request renderer,
agent contract, response schema, exact model/revision, reasoning and sampling
settings, tokenizer, normalizer, reservation calculator, and every per-dispatch
limit are immutable execution authority within one run.
`re continue` may raise only run-wide token
or active-time authorization; it cannot change this authority. These controls
remain outside artifact identity, so a compatible provider or model change in a
later run does not change artifact keys. EGR-166 will define whether a receipt
from that other executor contract may be adopted. Executor validation occurs at
creation, recovery, planning, and lease execution; installation drift produces
the non-mutating unavailable state below before dispatch.

Protocol-2.2 `WorkTemplate` and `WorkItem` also pin the deterministic verifier
ID, version, and implementation digest used by `CertificationKeyV2`. Creation,
recovery, and certification require the installed verifier to match. This is
certification authority outside artifact identity; legacy template/item bytes
remain unchanged.

An installed executor, renderer, tokenizer, calculator, normalizer, agent,
response schema, or verifier that is missing or does not match its pinned digest
puts an existing run in operational state `pinned_authority_unavailable`. This
check occurs before ledger/event mutation, reservation, or provider execution.
It is not a `work_item_failed` or `executor_failed` fact because restoring the
exact pinned installation makes continuation safe again. Status identifies every
missing/mismatched authority and the expected digest. Run creation fails without
publishing a manifest when the same condition exists initially. A matching
executor that actually violates its reservation or limit at runtime remains a
durable executor failure under the separate contract below. Read-only status can
always validate canonical objects, hashes, receipts, and terminal events without
executing the missing implementation; an already terminal run keeps its terminal
outcome and reports the mismatch only as an operational warning. The unavailable
state gates unresolved execution or certification, not historical inspection.

## Canonical Deterministic Artifact Schemas

Every protocol-2.2 catalog and deterministic artifact is strict canonical JSON:
duplicate keys, non-finite numbers, unknown fields, invalid Unicode, and schema-
invalid nulls are rejected. Arrays whose order has no semantic meaning are
sorted by the tuple named below and must be unique. No schema embeds its own
content hash. Hashes are computed over the final v2 canonical UTF-8 bytes and
stored in the manifest, artifact key, dependency, or ledger envelope that refers
to the object.

The artifact-policy catalog has exactly `schema_version: 1` and `entries`. Entries
are sorted by `(layer,artifact_kind)` and have exactly:

```text
ArtifactPolicyEntry = {
  artifact_kind: string,
  layer: "L0" | "L1",
  content_policy_version: string,
  selection_policy_version: string | null,
  artifact_schema_version: positive integer,
  producer_protocol_version: string,
  result_contract_id: string,
  canonicalization_id: string,
  byte_estimator_id: "utf8-byte-upper-bound-v1",
  max_canonical_json_bytes: positive integer,
  max_rendered_markdown_bytes: positive integer | null,
  max_context_bundle_bytes: positive integer | null,
  max_conservative_input_tokens: positive integer | null,
  required_surfaces: [string, ...],
  evidence_rule_id: string,
  ownership_rule_id: string,
  minimum_utility_rule_id: string | null,
  policy_parameters: PolicyParameters
}

PolicyParameters = EvidencePackPolicyParametersV1 |
                   ContextBundlePolicyParametersV1 |
                   CompactBaselinePolicyParametersV1 |
                   EmptyPolicyParametersV1

EvidencePackPolicyParametersV1 = SourceEvidencePackPolicyParametersV1 |
                                 DomainEvidencePackPolicyParametersV1

SourceEvidencePackPolicyParametersV1 = {
  parameter_schema: "evidence-pack-policy-parameters-v1",
  scope_kind: "source",
  allocation_protocol_id: "evidence-pack-allocation-v1",
  role_priority: ["declared_entry_point", "build_runtime",
                  "explicit_supporting", "documentation"],
  path_classifiers: [{
    role: "declared_entry_point" | "build_runtime" |
          "explicit_supporting" | "documentation",
    patterns: [string, ...]
  }, ...],
  omission_reason_codes: ["policy_ineligible", "non_text",
                          "line_too_large", "capacity_exhausted"]
}

DomainEvidencePackPolicyParametersV1 = {
  parameter_schema: "evidence-pack-policy-parameters-v1",
  scope_kind: "domain",
  allocation_protocol_id: "evidence-pack-allocation-v1",
  role_priority: ["explicit_supporting", "entry_point", "production", "test",
                  "documentation", "other"],
  path_classifiers: [{
    role: "explicit_supporting" | "entry_point" | "production" | "test" |
          "documentation" | "other",
    patterns: [string, ...]
  }, ...],
  omission_reason_codes: ["policy_ineligible", "non_text",
                          "line_too_large", "capacity_exhausted"]
}

ContextBundlePolicyParametersV1 = {
  parameter_schema: "context-bundle-policy-parameters-v1",
  target_artifact_kind: "domain-baseline" | "source-overview",
  target_policy_hash: string,
  projection: {
    protocol_id: "domain-projection-v1",
    surface_priority: ["responsibilities", "entry_points",
                       "external_contracts"],
    max_canonical_bytes_per_domain: 2048,
    max_total_canonical_bytes: 32768
  } | null
}

CompactBaselinePolicyParametersV1 = {
  parameter_schema: "compact-baseline-policy-parameters-v1",
  artifact_kind: "domain-baseline" | "source-overview",
  surface_order: [string, ...],
  max_claims_per_observed_surface: 24,
  max_evidence_refs_per_claim: 8,
  max_unknowns: 32,
  max_inspected_refs_per_unknown: 8,
  min_conflicting_evidence_refs: 2,
  min_statement_utf8_bytes: 1,
  max_statement_utf8_bytes: 1024,
  min_question_utf8_bytes: 1,
  max_question_utf8_bytes: 512,
  raw_candidate_size_multiplier: 2,
  minimum_utility_rule_id: "compact-v1-minimum-utility-v1"
}

EmptyPolicyParametersV1 = {}
```

`policy_parameters` is not an extension map. The artifact kind and content-
policy version select exactly one branch above. A source evidence-pack entry
requires the source branch and a domain evidence-pack entry the domain branch,
so an unrelated classifier change cannot re-key the other scope. Evidence
classifiers contain each literal role exactly once in `role_priority` order;
their normalized glob patterns are sorted and unique. A domain
context requires null `projection`; a source-overview context requires the
literal projection object. A compact domain entry requires the literal domain
surface order defined below; a compact source entry requires the literal source
surface order. In every compact entry, `surface_order` byte-equals
`required_surfaces` and the nested/top-level minimum-utility IDs match. In every
context entry, the nested target kind and policy hash match the top-level target
contract. Only deterministic inventory, partition, and root policies may use
the exact empty object. The loader rejects an unknown policy version, branch,
field, role, pattern form, order, or literal rather than preserving opaque
parameters. The complete canonical entry, including every classifier pattern
and parameter, is the input to `layer_policy_hash`.

The workspace partition catalog has exactly `schema_version: 1`, `snapshot_id`,
`source_selection_policy_version`, `partitioner`, `ownership_policy`, and
`sources`. `sources` are sorted by `source_id` and have this exact shape:

```text
SourceDescriptor = {
  source_id: string,
  workspace_relative_path: string,
  snapshot_id: string,
  source_content_id: string,
  source_partition_id: string,
  files: [FileRecord, ...],
  source_supporting_paths: [string, ...],
  domains: [DomainDescriptor, ...]
}

FileRecord = {
  source_relative_path: string,
  mode: "100644" | "100755" | "120000" | "160000",
  object_kind: "regular" | "symlink" | "gitlink",
  content_hash: string,
  byte_count: nonnegative integer,
  line_count: nonnegative integer,
  text_status: "eligible_utf8" | "contains_nul" | "invalid_utf8" |
               "non_regular"
}

DomainDescriptor = {
  domain_key: string,
  presentation_domain_id: string,
  source_relative_root: string,
  owned_file_count: nonnegative integer,
  owned_line_count: nonnegative integer,
  supporting_file_count: nonnegative integer,
  domain_content_id: string,
  domain_partition_id: string,
  owned_domain_relative_paths: [string, ...],
  supporting_source_relative_paths: [string, ...]
}

DomainPartitionDescriptor = {
  domain_key: string,
  presentation_domain_id: string,
  source_relative_root: string,
  domain_partition_id: string,
  owned_domain_relative_paths: [string, ...],
  supporting_source_relative_paths: [string, ...]
}

SourcePartitionIdentityInput = {
  source_id: string,
  partitioner: {id: string, version: string, implementation_digest: string},
  ownership_policy: {id: string, version: string,
                     implementation_digest: string},
  source_supporting_paths: [string, ...],
  domains: [DomainPartitionDescriptor, ...]
}
```

`partitioner` and `ownership_policy` each contain exactly an ID, version, and
implementation digest. File records and path arrays use normalized snapshot
paths governed by the existing source-snapshot schema and are sorted bytewise by
canonical UTF-8 path. Domain descriptors are sorted by `domain_key`.
`line_count` is zero for an empty regular blob and otherwise one plus the count
of LF bytes, minus one when the blob ends in LF; it is zero for non-regular
objects. Symlink targets and gitlinks are recorded but never followed or treated
as text. `eligible_utf8` means a regular blob that decodes as strict UTF-8 and
contains no NUL byte. Every other status is explicit selection debt when the
file is in a pack's declared inventory. Every digest in these schemas is a full
lowercase `sha256:<64-hex>` value over the named canonical bytes unless the
existing snapshot schema explicitly supplies a stronger tagged digest.

Mode and kind are a closed pair: `100644` and `100755` require `regular`,
`120000` requires `symlink`, and `160000` requires `gitlink`. A regular record
requires `eligible_utf8`, `contains_nul`, or `invalid_utf8`; a symlink or gitlink
requires `non_regular`. `source_partition_id` is the digest of the exact
`SourcePartitionIdentityInput` bytes. Its partitioner, ownership policy,
source-support set, and domain array byte-match the workspace catalog; domains
are sorted by `domain_key`. `DomainPartitionDescriptor` deliberately excludes
`domain_content_id`, byte counts, and line counts, so a content-only edit cannot
change source-partition bytes under a stable partition key.

L0 inventory artifacts contain exactly `schema_version`, `artifact_kind`,
`scope`, `partition_id`, and `files`. Their `files` are the applicable
`FileRecord` values with an additional `ownership` field equal to `source`,
`owned`, or `shared_supporting`; they are sorted by
`(source_relative_path,ownership)`. The L0 source-partition artifact contains
exactly `schema_version`, `artifact_kind`, `source_scope`,
`source_partition_id`, `partitioner`, `ownership_policy`,
`source_supporting_paths`, and `domains`. Its `domains` are the catalog's exact
`DomainPartitionDescriptor` projections, not the content-bearing
`DomainDescriptor` objects. These artifacts copy exact catalog values and cannot
reinterpret ownership. Changing source support, domain support, membership,
ownership, presentation assignment, or a partitioner/ownership implementation
therefore changes both source-partition bytes and `source_partition_id`;
changing only blob content changes neither.

An evidence pack has this exact shape:

```text
EvidencePack = {
  schema_version: 1,
  artifact_kind: "source-evidence-pack" | "domain-evidence-pack",
  scope: ArtifactScope,
  layer_policy_hash: string,
  inventory_artifact_hash: string,
  byte_estimator_id: "utf8-byte-upper-bound-v1",
  max_canonical_json_bytes: positive integer,
  max_conservative_input_tokens: positive integer,
  excerpts: [EvidenceExcerpt, ...],
  depth_debt: DepthDebt
}

EvidenceExcerpt = {
  evidence_authority_id: string,
  source_relative_path: string,
  ownership: "source" | "owned" | "shared_supporting" |
             "domain_projection",
  origin_domain_key: string | null,
  mode: string,
  source_blob_hash: string,
  start_line: positive integer,
  end_line: positive integer,
  raw_excerpt_hash: string,
  text_lf: string,
  complete_file: boolean
}

EvidenceAuthorityDescriptorV1 = {
  source_id: string,
  source_relative_path: string,
  authority_kind: "direct" | "domain_projection",
  origin_domain_key: string | null
}
```

Evidence excerpts are sorted by
`(source_relative_path,start_line,end_line,ownership,origin_domain_key)`. An L0
pack never uses `domain_projection`; that value is reserved for source-overview
context; null sorts before a non-null domain key. An excerpt is a complete
original-line prefix of one `eligible_utf8`
regular file. Lines are numbered by LF delimiters in the raw blob. The controller
strictly decodes the selected raw bytes as UTF-8 and replaces only CRLF sequences
with LF in `text_lf`; it does not apply Unicode normalization or reinterpret lone
CR bytes. `raw_excerpt_hash` covers the unmodified selected bytes, including
their original line endings. The certifier reconstructs both representations
from the pinned blob. Non-UTF-8, NUL-containing, symlink, and gitlink content is
never copied into `text_lf` and remains visible in `depth_debt`.

`evidence_authority_id` is the full digest of the canonical
`EvidenceAuthorityDescriptorV1`. A source-pack excerpt uses `direct` with null
origin. A domain-pack or domain-context excerpt uses `direct` with its target
domain key, whether its ownership is `owned` or `shared_supporting`. A source-
overview projection excerpt uses `domain_projection` with its origin domain key.
The descriptor source ID is the enclosing scope source. The ID, path, ownership,
and origin fields must agree; the same physical path may therefore have distinct
direct and per-domain projected authorities without collision.

`max_conservative_input_tokens` equals the UTF-8 byte ceiling under
`utf8-byte-upper-bound-v1`. Both caps are checked against the final canonical
object after each proposed allocation. `DepthDebt` is the exact type defined by
`compact-v1` below; its descriptor digest covers every non-selected file or
line-range descriptor, including the deterministic reason code
`policy_ineligible`, `non_text`, `line_too_large`, or `capacity_exhausted`.

A context bundle has exactly:

```text
ContextBundle = {
  schema_version: 1,
  artifact_kind: "domain-context-bundle" |
                 "source-overview-context-bundle",
  target_artifact_kind: "domain-baseline" | "source-overview",
  scope: ArtifactScope,
  context_policy_hash: string,
  target_policy_hash: string,
  target_artifact_policy: ArtifactPolicyEntry,
  dependencies: [{artifact_kind: string, artifact_hash: string}, ...],
  evidence_pack_hash: string,
  evidence: [EvidenceExcerpt, ...],
  domain_projections: [DomainProjection, ...],
  depth_debt: DepthDebt
}

DomainProjection = {
  domain_key: string,
  presentation_domain_id: string,
  baseline_artifact_hash: string,
  baseline_depth_debt: DepthDebt,
  baseline_depth_debt_hash: string,
  claims: [{surface: string, claim: Claim}, ...],
  evidence: [EvidenceExcerpt, ...],
  retained_claim_count: nonnegative integer,
  omitted_claim_count: nonnegative integer,
  omitted_claim_descriptor_hash: string | null
}
```

Dependencies are sorted by `(artifact_kind,artifact_hash)`; projections are
sorted by `domain_key`. A domain bundle has an empty `domain_projections` array.
A source-overview bundle may use source-pack excerpts in `evidence` and exact
same-source domain excerpts in its projections. Projection excerpts use
`ownership: domain_projection` and the matching non-null `origin_domain_key`.
`evidence_pack_hash` must occur exactly once in dependencies, every direct input
required by the production graph must occur there, and no unrelated dependency
is permitted. Every copied excerpt must byte-match its accepted source pack or
the original snapshot excerpt reconstructed from the accepted domain baseline's
context; every projected baseline hash must likewise occur exactly once in
dependencies.
Projection claims follow the pinned surface priority and then the accepted claim
array index; projection evidence follows the `EvidenceExcerpt` order.
`baseline_depth_debt` byte-matches the accepted domain baseline and
`baseline_depth_debt_hash` is its canonical digest. `retained_claim_count` equals
the claim-array length.
`omitted_claim_descriptor_hash` is null exactly when `omitted_claim_count` is
zero and otherwise hashes the ordered omitted `(surface,claim-index,claim-hash)`
descriptors.
`context_policy_hash` is the context bundle ArtifactKey's policy hash.
`target_artifact_policy` must match `target_artifact_kind` and hash to
`target_policy_hash`; the eventual provider artifact uses that target hash in
its own ArtifactKey and envelope. The context-policy entry's closed parameters
also pin that exact target policy hash, so a target-policy change necessarily
re-keys the context bundle without affecting L0. Separating the two prevents one
policy digest from pretending to identify two artifact kinds. Neither the bundle
nor the provider candidate embeds the context bundle's own hash, avoiding self-
reference; the resulting bundle hash becomes the baseline's direct dependency
after construction. When a domain claim is retained in a source-overview
projection, the context builder rewrites each direct domain
`evidence_authority_id` to the corresponding projected authority ID while
preserving path, line range, statement, and semantic claim order. It rejects a
claim unless every rewritten reference resolves to exactly one copied projection
excerpt. Omission claim hashes cover the original accepted domain claim bytes,
before this authority-only projection rewrite.

The deterministic source root has exactly:

```text
SourceBaselineRoot = {
  schema_version: 1,
  artifact: {
    artifact_kind: "source-baseline-root",
    layer: "L1",
    scope: ArtifactScope,
    partition_id: string,
    layer_policy_hash: string,
    dependency_hashes: [string, ...]
  },
  overview_artifact_hash: string,
  domains: [{
    domain_key: string,
    presentation_domain_id: string,
    baseline_artifact_hash: string
  }, ...]
}
```

Dependency hashes are sorted and unique; domains are sorted by `domain_key`.
The overview hash and every domain hash must occur exactly once in dependency
hashes. The root contains no certification IDs, rendered prose, mutable paths,
provider metadata, or execution observations.

## Production Artifact Graph

For every declared source, the graph contains:

```text
L0 source-inventory + L0 source-partition
    -> L0 source-evidence-pack

for each domain:
    L0 domain-inventory
        -> L0 domain-evidence-pack
        -> L1 domain-context-bundle
        -> L1 domain-baseline

L0 source-evidence-pack + all accepted L1 domain-baselines
    -> L1 source-overview-context-bundle
    -> L1 source-overview

L1 source-overview + all accepted L1 domain-baselines
    -> L1 source-baseline-root
```

Evidence packs and context bundles are ordinary content-addressed graph
artifacts with deterministic in-process producers and controller certification;
they are not provider candidates. Context bundles remain object-store inputs and
are not user-facing materialized baseline documents.

The source inventory is keyed only by `source_content_id`. The source partition
uses a null content ID and is keyed only by `source_partition_id`. Each domain
inventory is keyed independently by `domain_content_id` and
`domain_partition_id`, and materializes the exact owned/supporting file
inventory.

The deterministic `evidence-pack-v1` producer selects bounded original-line
excerpts from those inventories using the exact `EvidencePack` and
`EvidenceExcerpt` schemas above. Selection is stable across input ordering,
never follows links, and stops before the pinned canonical-byte ceiling. The
provider-neutral conservative-token ceiling is the same one-token-per-final-
UTF-8-byte bound and therefore cannot introduce adapter-dependent selection. The
pack records total, selected, partially selected, and omitted file/range counts
plus a digest of the omitted descriptor set. Omission is explicit depth debt,
never evidence that the omitted source has no behavior.

`evidence-pack-v1` uses this exact allocation protocol:

1. Every inventory file is classified exactly once. Eligible domain text files
   become selection candidates. Eligible source files become candidates only
   when classified as a source-level manifest, build/runtime configuration,
   documentation root, declared entry point, or supporting file. All remaining
   files are omitted debt with `non_text` or `policy_ineligible`; their role
   classifier and path patterns are part of the policy entry.
2. Candidate descriptors are ordered by pinned role priority and then normalized
   path. Source priority is declared entry point, build/runtime manifest or
   configuration, explicit supporting file, then documentation. Domain priority
   is explicit supporting file, declared or recognized entry point, production
   source, test, documentation, then other eligible text. An empty eligible file
   is fully selected without an excerpt. For every other candidate in that
   order, the producer proposes a one-complete-line prefix and serializes the
   whole provisional pack, including updated debt. A fitting proposal is
   retained; a non-fitting first line is omitted as `line_too_large` or
   `capacity_exhausted` according to whether it can fit in an otherwise empty
   pack.
3. Remaining canonical-byte capacity is divided equally across retained nonempty
   files using canonical serialized-byte delta, not raw-source length. Each file
   extends its retained prefix with the longest sequence of complete subsequent
   lines that fits its share. The producer never splits a line.
4. Unused shares are redistributed in normalized-path round-robin passes, adding
   subsequent complete lines to each retained prefix until no addition fits the
   provider-neutral canonical-byte/conservative-token caps.
5. The producer serializes after each proposed addition; the canonical object,
   rather than raw source bytes, is what must remain under the pinned ceiling.

The allocation protocol and role classifier are part of the complete hashed L0
policy entry. Changing either produces a new evidence pack and downstream L1
key without changing existing inventory keys.

A deterministic L1 domain-context-bundle artifact depends on the exact accepted
domain-inventory and domain-evidence-pack hashes. The domain baseline depends
directly on that bundle hash, so its dependency closure remains domain-local.
Changes in an unrelated domain therefore do not invalidate it.

The source overview is dispatched only after all required domain baselines are
accepted. Its deterministic context-bundle artifact contains the bounded source
evidence pack and a controller-generated bounded projection of accepted domain
baselines. The projection has per-domain and total caps, uses stable-domain-key
order, and records omitted-domain count and descriptor digest when every domain
summary cannot fit. `compact-v1` permits at most 2 KiB of canonical projection
per domain and 32 KiB across all domain projections. It never contains the full
source tree or concatenated complete domain artifacts. The bundle depends on the
source inventory, source partition, source evidence pack, and every accepted
domain artifact hash; the overview depends directly on that bundle. It describes
only source-wide structure and relationships; it does not duplicate domain
specifications or perform workspace synthesis.

The context builder also computes the exact domain-debt rollup and complete
retained/omitted projection-claim debt defined below. It carries each retained
domain's full compact depth-debt object, not only its hash. Whole-domain and
per-domain claim omissions contribute to the overview `DepthDebt` before the
provider dispatch, so the model and later status output can distinguish thin
domain evidence from a complete projection.

Each domain projection contains only stable domain identity, baseline artifact
hash, exact baseline depth debt and digest, and the first claims that fit—in
surface priority order
`responsibilities`, `entry_points`, then `external_contracts`, preserving the
provider's accepted within-surface semantic order—together with the exact
evidence excerpts needed to cite those claims. The baseliner contract requires
the most material claim first within each surface; lexical sorting is forbidden
because it would discard that salience signal. A claim whose complete evidence
cannot fit is omitted with the projection debt; the projection never carries an
uncitable statement. Source-overview claims must still cite those included
snapshot excerpts, not the prior model statement.

`source-baseline-root` is generated in process after the source overview and
every selected domain baseline is accepted. Its canonical JSON records the
source scope, partition identity, policy hash, exact overview hash, sorted
stable-domain-key/artifact-hash entries, and the pinned presentation-ID values. It
contains no generated prose and no certification receipt IDs. The controller's
deterministic invocation validates each dependency's accepted certification and
artifact-acceptance receipt before constructing those bytes. Provider candidate
provenance remains in each dependency's candidate-assessment and
`artifact_accepted` event rather than being copied into the root or a second
assembly event. Re-certifying unchanged artifacts therefore cannot produce
different root bytes under the same artifact key.

A changed L1 policy produces different L1 keys and source roots while leaving
all L0 keys unchanged. A changed source file invalidates only L0/L1 artifacts
whose declared read set contains that file, followed by source overview/root as
required by their dependency hashes. A changed partition invalidates only its
source partition, affected domain inventories, and their downstream closure.
Later EGR-166 work may adopt independently certified matching receipts into a
new run; EGR-165 itself performs no cross-run lookup or object reuse.

## Creation and Goal Semantics

For protocol 2.2, `echelon re run --engine v2` requests the fixed `baseline`
goal by default. Its dependency closure contains all required L0 and L1 nodes
for every declared source and domain. `--goal inventory` remains available as
an explicit L0-only diagnostic; `--goal baseline` is the explicit form of the
default. No other goals, source filters, domain filters, or depth profiles are
accepted by EGR-165.

`--shadow` builds, validates, and explains the exact selected graph without
provider dispatch. It still resolves and validates the configured L1 adapter
when the selected goal is `baseline`, because a shadow run must not pin an
executor contract that cannot later be recovered. Continuation always uses the
immutable requested goal and rejects creation-only goal switches.

For a baseline goal, shadow output also reports the exact initial dispatch
count, the maximum shared-retry dispatch count, each statically constructible
context bundle's canonical byte size and conservative input-token estimate, the
worst-case source-overview bundle bounds, and the pinned executor request
limits. The controller applies `bounded-dispatch-v1` to each statically
constructible provider-request envelope and the pinned worst-case input to later
overview requests,
then reports maximum initial-path and shared-retry token and active-time
reservations for the whole run. It distinguishes estimated, reserved, and
observed usage. A budget smaller than the maximum is allowed so a run may make
bounded partial progress, but the preflight must state that the authorization
cannot cover the worst case. Shadow mode performs no provider call and incurs no
provider-token usage.

This fixed goal selector preserves an inexpensive deterministic diagnostic
without pre-empting EGR-169's selective deepening interface.

## L1 Baseline Content Contract

The new neutral `echelon.re-baseliner` agent contract produces one authorial
payload per dispatch. It follows the dispatcher/protocol split: the controller
supplies the exact context pack and scope, while the agent file owns invariant
production rules. An eligible filesystem adapter lets the provider write the
one candidate file. `bounded-api-baseline-v1` instead persists the provider's
single strict JSON response byte-for-byte as that file. In both transports the
same candidate schema and controller certification apply; transport code, not
provider prose, owns process status and durable capture.

Before every dispatch the controller accepts and persists one deterministic,
canonical scoped context-bundle artifact. Its content hash is the provider
artifact's explicit direct dependency; the provider never has to reproduce it.
Recovery either verifies that exact artifact and deterministic certification or
rebuilds identical bytes from already accepted dependencies before dispatch.
The bundle contains only:

- bounded excerpts from the accepted source or domain evidence pack;
- canonical L0 dependency metadata;
- for source overview only, a bounded deterministic projection of accepted
  domain baselines;
- the pinned `compact-v1` schema and content policy; and
- explicitly supplied controller identity and depth-debt metadata.

`compact-v1` caps a domain context bundle at 128 KiB of canonical UTF-8 and a
conservative 131,072 input tokens. It caps a source-overview bundle at 96 KiB
and 98,304 conservative input tokens, including all domain projections. The
bundle's conservative count always uses `utf8-byte-upper-bound-v1`. The adapter
separately tokenizes the complete provider-request envelope, including agent
instructions, response schema, and framing outside the bundle, for execution
preflight. If the pinned adapter has no exact tokenizer, the same one-byte/one-
token upper bound plus pinned framing bound is used. A request exceeding
either pinned bundle limit, the provider context window, or its computed
billable-token reservation is rejected before lease execution. Neither exact
tokenization nor provider choice may change bundle bytes. Raising a run budget
cannot enlarge these content-policy limits; that requires a separately keyed
higher-layer policy.

The agent contract instructs the provider to consume only that bundle and return
only the authorial payload. An eligible filesystem adapter receives the bundle
as read authority and the candidate directory as write authority. The bounded
API adapter embeds or supplies the same bundle through its immutable request and
has no host filesystem tools. A future adapter without equivalent host
isolation may rely on behavioral confinement, but acceptance authority still
requires every factual claim and evidence reference to resolve inside the
pinned bundle. Such an adapter cannot claim technical read isolation.

The agent never writes controller state, the ledger, events, materialized
output, workspace synthesis, or sibling artifacts. The controller rejects any
candidate tree containing files outside the one-file result contract.

Each provider candidate contains exactly one regular file:

- `baseline.json`, containing only the model-authored compact content payload.

The candidate does not contain artifact identity, dependencies, coverage,
depth-debt, provider metadata, or a controller verdict. The parser rejects
duplicate keys, non-finite numbers, invalid Unicode, unknown fields, and content
outside the authorial schema. The controller normalizes the valid payload,
injects all controller-owned fields, and serializes the complete artifact with
the existing v2 canonical JSON serializer. Canonical controller bytes—not
provider whitespace, object-key ordering, or metadata echoes—are the artifact
and certification input. Raw candidate size is capped at twice the final
canonical artifact limit before parsing.

After any execution, the controller captures bytes before interpreting its
result. For provider work, candidate file blobs are persisted without following
links; the candidate inventory, retained stdout blob, and any provider-usage
blob are then fsynced before the execution capture that refers to them. For
deterministic work, the produced artifact object or captured failure and the
retained empty-or-diagnostic stdout blob are durable first. The strict canonical
object schemas are:

```text
CandidateInventoryEntry = {
  relative_path: string,
  object_kind: "regular" | "symlink" | "special",
  mode: integer in [0, 4095],
  byte_count: nonnegative integer,
  content_hash: string | null
}

CandidateInventory = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  entries: [CandidateInventoryEntry, ...]
}

ExecutionCapture = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  execution_input_hash: string,
  executor_contract_hash: string,
  execution_mode: "in_process" | "api",
  result_kind: "provider_candidate" | "deterministic_artifact" | "none",
  candidate_inventory_hash: string | null,
  deterministic_artifact_hash: string | null,
  stdout_digest: string,
  stdout_blob_hash: string,
  stdout_byte_count: nonnegative integer,
  stdout_retained_byte_count: nonnegative integer,
  stdout_capture: "complete" | "terminal_tail",
  stderr_digest: string | null,
  provider_usage_blob_hash: string | null,
  started_at: RFC3339 timestamp,
  ended_at: RFC3339 timestamp,
  duration_ms: nonnegative integer,
  exit_code: integer | null,
  timed_out: boolean,
  output_truncated: boolean,
  provider_name: string,
  resolved_model_revision: string | null
}

ExecutionCaptureCommitV1 = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  execution_input_hash: string,
  execution_capture_hash: string
}

PersistedCandidateV2 = {
  schema_version: 2,
  dispatch_id: string,
  work_item_id: string,
  execution_capture_hash: string,
  candidate_inventory_hash: string
}
```

Inventory entries are sorted by `relative_path`; regular entries require a
content hash and persisted blob, while symlink and special entries require null.
`stdout_digest` covers the complete raw stdout bytes. At most the final 128 KiB
is retained as the content-addressed stdout blob; `complete` requires equal byte
counts and matching digest, while `terminal_tail` requires a larger original
count and sets `output_truncated`. Result parsing is permitted from a terminal
tail only when it contains one complete unambiguous terminal result block;
otherwise the raw result contract is invalid. `resolved_model_revision` is
required for provider-backed execution and must equal the executor contract;
deterministic work requires null.

API work requires `execution_mode: api`, `result_kind: provider_candidate`, a
non-null candidate inventory, and a null deterministic artifact. The inventory
may be empty when transport returned no candidate, but its empty canonical object
is still durable. Deterministic work requires `execution_mode: in_process`, null
candidate inventory, and either `result_kind: deterministic_artifact` with the
exact produced object hash or `result_kind: none` with no artifact hash after a
captured in-process failure. A successful deterministic object is certified
directly; it never receives candidate, result-reconstruction, or candidate-
assessment events. CLI capture is not admitted by protocol 2.2 because no CLI
executor is initially eligible.

For API work, the `candidate_id` is the digest of the exact canonical
`PersistedCandidateV2`; it contains no path or timestamp. Its fields byte-match
the committed capture and inventory. The candidate record is fsynced before the
controller appends the exact event payload `{candidate_id, dispatch_id,
work_item_id, execution_capture_hash, candidate_inventory_hash}`. Deterministic
work never creates this record or `candidate_persisted` event.

When the provider supplies usage, the adapter persists its lossless canonical
usage record under `provider_usage_blob_hash` before the capture. Its exact
adapter-specific schema is pinned by the token-accounting normalizer. Unavailable
usage requires null. Token status and normalized counts are derived from that
stored object during event construction and recovery, never only from transient
adapter fields.

Only after those objects are durable does the controller write and fsync one
canonical `ExecutionCapture`, write `v2/captures/.staging/<dispatch-id>/ready.json`
containing the exact `ExecutionCaptureCommitV1`, fsync that staging directory,
and publish the same bytes without clobber at
`v2/captures/committed/<dispatch-id>.json`. The final commit path is the unique
authority associating a dispatch with a capture. Its directory is fsynced before
any observation event. Both staging and committed paths use validated safe
dispatch IDs, directory-relative no-follow operations, regular files, and exact
mode/hash checks; symlinks, aliases, and conflicting ready/commit bytes fail
closed. The controller then evaluates file and raw result
contracts and appends `dispatch_observed`, referencing the exact
`execution_capture_hash` and recording
`raw_result_contract_status: "valid" | "invalid" | "not_applicable"`.
`not_applicable` is required exactly for deterministic in-process work; provider
work requires valid or invalid. Thus the persisted capture
contains observations, not a prematurely derived `result_contract_valid`
boolean. This preserves a valid candidate across process exit, controller crash,
result parsing, and recovery rather than making a prose wrapper the only proof
that output exists. A capture or inventory mismatch fails closed; it is never
replaced by current process output.

Recovery applies this exact state table before planning:

1. No `dispatch_started`: discard or reuse a complete prepared ExecutionInput;
   no execution or reservation has occurred.
2. `dispatch_started` plus a valid committed capture: validate the complete
   capture closure and append any missing `dispatch_observed`, candidate, or
   deterministic certification transitions without executing the provider.
3. `dispatch_started` plus a valid staging `ready.json` but no committed path:
   validate every referenced byte and finish the no-clobber commit, then apply
   case 2. A conflicting committed path fails closed.
4. `dispatch_started` with neither complete authority above and no matching live
   lease/process under the exclusive run lock: append one `dispatch_abandoned`
   event, charge the full token and active reservations, quarantine any
   incomplete run-local staging references, and never execute that dispatch ID
   again. A matching live owner leaves recovery unavailable rather than racing
   it. Content-addressed blobs without a complete capture commit remain non-
   authoritative garbage eligible for later safe collection.

The protocol-2.2 `dispatch_abandoned` payload has exactly `dispatch_id`,
`work_item_id`, `execution_input_hash`, `executor_contract_hash`, and
`reason_code: "execution_outcome_indeterminate"`. It sets the effective result
status to `indeterminate`, consumes the already-started attempt, and authorizes a
`result_contract_retry` only for provider work when the shared retry remains.
That retry receives a new dispatch ID and is reported as an additional provider
call, not as replay of the abandoned dispatch. If no provider retry remains, or
for deterministic work whose retry limits are zero, the item receives terminal
`execution_indeterminate` failure with the abandonment event as its authority;
it does not falsely blame a result parser or shared executor. EGR-165 therefore
guarantees at-most-once external provider execution per dispatch ID, not
impossible exactly-once execution of a logical work item across an external API
response-before-commit crash. A future adapter may strengthen this with a
provider idempotency/retrieval contract, but status and tests may not infer it.

The controller renders `baseline.md` deterministically from accepted canonical
JSON during materialization. Markdown is therefore a derived projection, not a
second provider-authored artifact or certification input. This avoids duplicate
model output, metadata-copy failures, formatting-only retries, and an otherwise
unverifiable narrative-equivalence contract.

### Exact `compact-v1` schema

The provider-authored `baseline.json` has exactly three top-level members and no
extension fields:

```text
{
  "schema_version": 1,
  "surfaces": DomainSurfaceMap | SourceOverviewSurfaceMap,
  "unknowns": [Unknown, ...]
}
```

After authorial validation and normalization, the controller constructs the
accepted artifact envelope with exactly four top-level members:

```text
{
  "schema_version": 1,
  "artifact": {
    "artifact_kind": "domain-baseline" | "source-overview",
    "layer": "L1",
    "scope": {
      "source_id": string,
      "domain_key": string | null,
      "content_id": string
    },
    "partition_id": string,
    "layer_policy_hash": string,
    "dependency_hashes": [string, ...],
    "context_bundle_hash": string
  },
  "surfaces": DomainSurfaceMap | SourceOverviewSurfaceMap,
  "unknowns": [Unknown, ...],
  "depth_debt": DepthDebt
}
```

All `artifact` and `depth_debt` values come directly from the pinned WorkItem,
accepted context bundle, and partition catalog. They never pass through provider
output. `dependency_hashes` are unique and sorted and include the exact context-
bundle hash exactly once and no other direct dependency not authorized by the
graph. Domain baselines require `domain_key`; source overviews require it
to be null. Presentation domain IDs exist only in the partition catalog, source
root, domain projections, and materialized path. They never enter reusable domain
artifact bytes or identity, so presentation renumbering cannot create two hashes
for one unchanged domain `ArtifactKey`.

A domain baseline has exactly these surfaces: `responsibilities`,
`entry_points`, `core_behavior`, `failure_paths`, `state_and_data`,
`external_contracts`, `tests`, and `operational_constraints`. A source overview
has exactly: `purpose`, `runtime_shape`, `major_entry_points`,
`intra_source_boundaries`, and `domain_relationships`. The complete domain-key
catalog remains in the deterministic source root; the overview does not copy it.

The map schemas are literal and admit no other key or missing key:

```text
DomainSurfaceMap = {
  responsibilities: Surface,
  entry_points: Surface,
  core_behavior: Surface,
  failure_paths: Surface,
  state_and_data: Surface,
  external_contracts: Surface,
  tests: Surface,
  operational_constraints: Surface
}

SourceOverviewSurfaceMap = {
  purpose: Surface,
  runtime_shape: Surface,
  major_entry_points: Surface,
  intra_source_boundaries: Surface,
  domain_relationships: Surface
}
```

The WorkItem target artifact kind selects exactly one map. A domain candidate
using the source map, a source candidate using the domain map, or a union of
their keys is invalid.

Every surface is exactly:

```text
Surface = {
  status: "observed" | "not_established",
  items: [Claim, ...],
  not_established_reason_code:
    "not_in_bounded_context" | "requires_deeper_analysis" | null
}

Claim = {
  statement: nonempty normalized string,
  evidence: [EvidenceRef, ...]
}

EvidenceRef = {
  evidence_authority_id: string,
  path: string,
  start_line: positive integer,
  end_line: positive integer
}

Unknown = {
  question: nonempty normalized string,
  reason_code:
    "not_in_bounded_context" | "conflicting_evidence" | "requires_deeper_analysis",
  inspected_evidence: [EvidenceRef, ...]
}
```

An `observed` surface has one to 24 unique claims and a null reason code. A
`not_established` surface has no claims and one non-null reason code; it means
only that the bounded context did not establish the surface. An affirmative
absence such as "this domain has no tests" is a factual claim and must use
`observed` with evidence. This removes the model-selected category of claims
that supposedly do not require evidence.

Every claim has one to eight unique evidence references. Every range is 1-based
and inclusive and requires `start_line <= end_line`; zero-width, reversed, or
half-open interpretations are rejected. Unknowns may have zero to eight
inspected references. They are rendered only as unresolved questions
and are never accepted or counted as established claims; semantic misuse of a
question remains explicitly unaudited until EGR-167. A `conflicting_evidence`
unknown requires two to eight inspected references; the other reason codes allow
zero to eight. The controller converts CRLF and lone CR in provider-authored
prose to LF, converts prose to Unicode NFC, and removes leading and trailing
Unicode whitespace. It resolves each evidence-authority ID to exactly one
authority descriptor and excerpt in the context bundle, then requires `path` to
byte-match that descriptor. A missing, mismatched, or non-resolving authority,
an out-of-excerpt range, and disallowed control characters are rejected.

Within each surface, claim array order is semantic and is preserved; the agent
must place the most material claim first. Unknown order is likewise preserved.
Evidence and inspected-evidence arrays are sorted by
`(evidence_authority_id,path,start_line,end_line)`. Claims, unknowns, and
evidence arrays must remain
unique after normalization; a post-normalization duplicate is rejected rather
than silently discarded. Statements must contain 1 to 1,024 canonical UTF-8
bytes and questions 1 to 512 bytes after trimming and normalization. Empty or
whitespace-only prose is rejected and therefore cannot satisfy an observed
surface or minimum-utility count. Unknowns are limited to 32, and identifiers
and paths to the limits pinned by the source-snapshot schema. All cardinality,
number, ordering, and byte limits are enforced after normalization and before
canonical serialization.

An evidence reference resolves only when its entire original line range exists
in the uniquely named context-bundle excerpt and the controller reconstructs
the excerpt and raw hash from the pinned snapshot blob. Merely existing in the
wider snapshot or sharing a path with another authority is insufficient. Scope
authorization is exact:

- a domain baseline may cite `owned` excerpts for its domain and
  `shared_supporting` excerpts explicitly listed in that domain's read set;
- a source overview may cite `source` excerpts and `domain_projection` excerpts
  carried by its same-source context bundle, including an excerpt that the
  projected domain was authorized to read as shared support even when a sibling
  domain owns the path;
- every artifact rejects evidence whose `source_id` differs from its scope; and
- a domain rejects a sibling-owned path unless the exact excerpt is separately
  tagged `shared_supporting` for the target domain in the immutable partition
  catalog and context bundle.

The broader snapshot, an unprojected sibling domain baseline, and a statement in
an accepted baseline are never evidence. Source-overview claims cite only the
original snapshot excerpts carried into the projection. Controller-supplied
identity, counts, and descriptor hashes require no provider citation; every
provider-authored factual statement appears only inside `Claim` and therefore
always carries evidence.

`compact-v1-minimum-utility-v1` is a deterministic acceptance gate in addition
to schema presence. A domain baseline must have an observed `responsibilities`
surface, at least one observed `entry_points` or `core_behavior` surface, and at
least one distinct cited regular snapshot file. A source overview must have
observed `purpose` and `runtime_shape` surfaces and at least one distinct cited
regular snapshot file. When its partition contains more than one domain, it
must additionally have at least one observed claim in
`intra_source_boundaries` or `domain_relationships`. An honest all-
`not_established` payload therefore cannot be labeled complete.

Failure of this gate is the artifact-contract diagnostic
`minimum_utility_not_met`. It may consume the one shared retry, but a second
failure becomes a durable failed work item with failure class `minimum_utility`
and the same reason code; it never produces an accepted artifact or a compact-
baseline-complete banner. The controller does not claim that bounded context was
the cause—the provider may simply have failed to use available evidence. This
gate checks only observed-surface and evidence cardinality. Whether the claims
are correct remains semantic-audit work for EGR-167.

`depth_debt` has the same exact shape in evidence packs, context bundles, and
both baseline artifact kinds:

```text
DepthDebt = {
  inventory_file_count: nonnegative integer,
  fully_selected_file_count: nonnegative integer,
  partially_selected_file_count: nonnegative integer,
  omitted_file_count: nonnegative integer,
  omitted_range_count: nonnegative integer,
  omitted_descriptor_hash: string | null,
  domain_depth_debt_rollup: DomainDepthDebtRollup | null,
  omitted_domain_summary_count: nonnegative integer,
  omitted_domain_descriptor_hash: string | null,
  retained_projected_claim_count: nonnegative integer,
  omitted_projected_claim_count: nonnegative integer,
  omitted_projected_claim_descriptor_hash: string | null
}

DomainDepthDebtRollup = {
  domain_count: nonnegative integer,
  inventory_read_set_entry_count: nonnegative integer,
  fully_selected_read_set_entry_count: nonnegative integer,
  partially_selected_read_set_entry_count: nonnegative integer,
  omitted_read_set_entry_count: nonnegative integer,
  omitted_range_count: nonnegative integer,
  domain_debt_descriptor_hash: string | null
}

OmittedEvidenceDescriptor = {
  descriptor_kind: "file" | "line_range",
  source_relative_path: string,
  ownership: "source" | "owned" | "shared_supporting",
  origin_domain_key: string | null,
  start_line: positive integer | null,
  end_line: positive integer | null,
  reason_code: "policy_ineligible" | "non_text" |
               "line_too_large" | "capacity_exhausted"
}

OmittedDomainDescriptor = {
  domain_key: string,
  baseline_artifact_hash: string,
  reason_code: "capacity_exhausted"
}

OmittedProjectedClaimDescriptor = {
  domain_key: string,
  surface: string,
  claim_index: nonnegative integer,
  claim_hash: string,
  reason_code: "capacity_exhausted"
}
```

Counts and hashes are copied by the controller from the accepted context bundle;
they never appear in the authorial candidate.
`fully_selected_file_count + partially_selected_file_count + omitted_file_count`
equals `inventory_file_count`. `omitted_descriptor_hash` is null only when both
omitted file and range counts are zero; otherwise it is the full descriptor
digest. It covers sorted unique `OmittedEvidenceDescriptor` values ordered by
`(source_relative_path,ownership,origin_domain_key,descriptor_kind,start_line,
end_line,reason_code)`. File descriptors require null line fields; range
descriptors require an inclusive ordered range.
`source` ownership requires a null origin domain; `owned` and
`shared_supporting` require the target domain key. Projection omission is
represented by the separate domain/claim descriptors rather than by assigning
`domain_projection` ownership here.

For a source or domain evidence pack, the file counts describe its exact direct
inventory, `domain_depth_debt_rollup` is null, and every domain-summary and
projected-claim field is zero/null. A domain context and accepted domain baseline
copy the domain evidence-pack debt unchanged. A source-overview context and
accepted overview use top-level file counts for only the direct source read set.
Their non-null rollup sums the accepted domain baseline read-set counts; shared
supporting paths may therefore count once per authorized domain read set and are
not misreported as unique workspace files. In that rollup,
`fully_selected_read_set_entry_count + partially_selected_read_set_entry_count +
omitted_read_set_entry_count` equals `inventory_read_set_entry_count`.
`domain_debt_descriptor_hash` covers sorted unique
`(domain_key,baseline_depth_debt_hash)` descriptors and is null exactly when
`domain_count` is zero and otherwise required.

The domain-summary hash covers sorted `OmittedDomainDescriptor` values and
follows the zero/null rule. The omitted projected-claim count includes claims
trimmed from retained projections and projection-priority claims belonging to a
wholly omitted domain summary. Its hash covers sorted
`OmittedProjectedClaimDescriptor` values and is null exactly when the count is
zero. The number of retained `domain_projections` plus
`omitted_domain_summary_count` equals the rollup's `domain_count`.
`retained_projected_claim_count + omitted_projected_claim_count` equals the
number of projection-priority claims in all accepted domain baselines, and the
retained count is the sum of retained claims across all projections. These
explicit objects and counts keep bounded selection visible to
the model, certifier, status renderer, and user without allowing opaque hashes or
omission to masquerade as coverage.

The policy limits canonical domain-baseline JSON to 32 KiB and source-overview
JSON to 48 KiB. It limits derived Markdown to 96 KiB. The trailing stdout
contract is deliberately minimal:

```yaml
echelon_result:
  schema_version: 1
  outcome: candidate_ready
```

It contains no path, hash, size, scope, dependency, verdict, or coverage echo.
The controller already owns the output directory and computes those facts from
persisted bytes. Evidence remains in `baseline.json` and is not emitted a second
time. A filesystem-agent transport may obtain this block from terminal stdout;
the trusted bounded API adapter emits it after persisting the response candidate.
In neither case does the block carry acceptance authority.

If the trailing block is absent or malformed but the isolated candidate tree
contains exactly one regular `baseline.json`, no other entries, and that file
passes strict authorial-schema parsing, the controller synthesizes a durable
`result_contract_reconstructed` event and continues artifact
certification without another provider call. Artifact-contract diagnostics found
after reconstruction remain artifact diagnostics. A valid trailing block with
an absent or invalid candidate consumes an artifact-contract retry. A missing or
malformed block consumes a result-contract retry only when no unique strict
authorial candidate can be reconstructed. Recovery repeats this classification
from the immutable candidate inventory, persisted candidate blobs, and retained
stdout blob validated against `ExecutionCapture`; a digest without retrievable
bytes is never treated as sufficient parsing authority. A crash therefore cannot
turn a recoverable candidate into a new provider attempt.

The protocol-2.2 `result_contract_reconstructed` payload has exactly
`dispatch_id`, `work_item_id`, `candidate_id`, and `result_contract_id`. It is
valid only after the matching immutable `candidate_persisted` event, only when
the recorded raw result status is invalid, and before candidate certification.
Applying the event sets the attempt's
`effective_result_contract_status` to `reconstructed`, clears result-contract-
retry eligibility, records `result_contract_source: reconstructed`, and leaves
the persisted candidate as the active certification input. Any later rejection
of that candidate is consequently eligible only for
`artifact_contract_retry`; it can never reopen `result_contract_retry`. Replay
derives and applies the same transition or rejects a conflicting one;
reconstruction never changes provider-attempt counters.

## Execution and Budget Behavior

Each L1 work item pins one initial generation plus one shared retry slot. The
literal limits are two provider attempts, one initial attempt, at most one
result-contract retry, at most one artifact-contract retry, one total retry of
either kind, and zero semantic-repair rounds. A missing or malformed trailing
result consumes `result_contract_retry` only when the controller cannot
reconstruct one unique strict authorial candidate. A present or reconstructed
result whose candidate fails authorial schema, final envelope bounds, evidence
scope, or minimum utility consumes `artifact_contract_retry` and receives only
normalized deterministic diagnostics plus the identical context bundle. The two
retry kinds can never both occur for one work item. Reconstruction consumes no
retry. Neither retry performs atomic or semantic repair.

Run-manifest schema 2 `BudgetPolicy` adds `shared_retry_limit` and
`artifact_contract_retry_limit`. Protocol-2.2 `WorkTemplate` and `WorkItem`
execution metadata add `max_shared_retries` and
`max_artifact_contract_retries`, and the event attempt-kind enum adds
`artifact_contract_retry`. For L1, `provider_attempt_limit` and
`artifact_generation_attempt_limit` are `2`; the shared, result-contract, and
artifact-contract retry limits are each `1`; semantic-repair limit is `0`; and
event validation still permits exactly one `initial_generation`. Both provider
retry kinds increment provider, artifact-generation, and shared-retry counters,
then their own kind-specific counter. Deterministic work has every retry limit
set to `0`, `max_provider_attempts: 0`, and `max_generation_attempts: 1`.
Provider L1 work uses the six exact WorkTemplate/WorkItem values `2`, `2`, `0`,
`1`, `1`, and `1` in provider, generation, semantic, result, shared, and artifact
order. The shared counter gates both retry-specific counters. Attempt dimensions
are enforced per WorkItem against both its copied limit and the matching run-
policy maximum; token and active-time authorization are run-wide. These are
execution controls, not artifact-key fields. Protocol 2.0/2.1 manifests, event
values, and canonical WorkTemplate representations remain byte-for-byte
unchanged.

When an item-level retry is exhausted or an indeterminate execution has no
authorized retry, the controller first appends this exact controller-owned
ledger receipt:

```text
WorkItemFailureReceipt = {
  schema_version: 1,
  work_item_id: string,
  dispatch_id: string | null,
  candidate_id: string | null,
  candidate_assessment_id: string | null,
  execution_capture_hash: string | null,
  dispatch_abandonment_event_hash: string | null,
  failure_class: "result_contract" | "artifact_contract" |
                 "minimum_utility" | "execution_indeterminate",
  reason_code: string,
  normalized_diagnostics: [nonempty normalized string, ...]
}

ExecutorFailureReceiptV1 = {
  schema_version: 1,
  executor_contract_hash: string,
  trigger_work_item_id: string,
  dispatch_id: string | null,
  candidate_id: string | null,
  execution_capture_hash: string | null,
  reason_code: "reservation_mismatch" | "limit_unenforceable" |
               "usage_exceeded_reservation" |
               "deterministic_execution_failed" |
               "deterministic_artifact_invalid",
  normalized_diagnostics: [nonempty normalized string, ...]
}
```

Diagnostics contain one to 64 sorted unique entries of at most 1,024 canonical
UTF-8 bytes each, and contain no timestamps, provider prose, or nondeterministic
stack addresses. Ordinary attempt exhaustion requires the final dispatch and
execution capture. Terminal loss of an indeterminate dispatch instead requires
the exact `dispatch_abandoned` event hash and a null capture. These two
authorities are mutually exclusive. Candidate fields are required exactly when
a candidate was persisted. The `failure_receipt_id` is the content digest of the
complete canonical receipt.

Executor safety is separate run authority rather than pretending that one item
owns a shared executor failure. A pre-dispatch reservation mismatch or
unenforceable limit uses null dispatch, candidate, and capture fields. A post-
dispatch usage, deterministic-execution, or deterministic-artifact breach
requires the triggering dispatch and capture; candidate ID is required only for
a captured provider candidate. The `executor_failure_receipt_id` is the complete
receipt digest. One executor-contract hash admits one byte-identical executor-
failure receipt; a second different receipt for an already failed executor is a
ledger conflict.

The ledger record type is `work_item_failure` and contains exactly the receipt.
It is fsynced before the controller appends protocol-2.2 `work_item_failed`; that
event does not immediately terminate the run. Its payload has exactly:

```text
{
  work_item_id: string,
  failure_class: "result_contract" | "artifact_contract" |
                 "minimum_utility" | "execution_indeterminate",
  reason_code: string,
  failure_receipt_id: string
}
```

An exhausted result retry uses `result_contract`. An exhausted artifact retry
uses `artifact_contract`, except that a repeated minimum-utility diagnostic uses
`minimum_utility`. An abandoned dispatch without an authorized retry uses
`execution_indeterminate`. Every event field must byte-match the referenced
receipt.

A provider, adapter, or deterministic-producer safety breach instead appends
ledger record type `executor_failure` containing exactly
`ExecutorFailureReceiptV1`, fsyncs it, and appends this exact event:

```text
executor_failed = {
  executor_contract_hash: string,
  executor_failure_receipt_id: string,
  trigger_work_item_id: string
}
```

The event fields byte-match the receipt. A candidate from a breaching dispatch
is persisted for forensics but cannot be certified or accepted because its
attempt exceeded pinned authority. The breach does not invalidate artifacts
accepted before it or prevent work bound to a different executor from
completing.

An event without its preceding validated receipt is invalid. A crash after
either receipt fsync but before its event leaves an orphan receipt; recovery
validates it against the immutable WorkItem, executor contract, and final
attempt/capture when applicable, then appends the one matching event
idempotently. A conflicting or premature orphan receipt fails closed. Replaying
the same receipt/event pair changes neither counters nor graph state a second
time.

The initial closed reason-code catalog is
`execution_outcome_indeterminate`, `result_unrecoverable`, `candidate_tree_invalid`,
`authorial_schema_invalid`, `artifact_bound_exceeded`,
`evidence_contract_invalid`, `minimum_utility_not_met`,
`reservation_mismatch`, `limit_unenforceable`, `usage_exceeded_reservation`,
`deterministic_execution_failed`, and `deterministic_artifact_invalid`.
`execution_outcome_indeterminate` belongs only to execution-indeterminate
failure; `result_unrecoverable` belongs only to result-contract failure;
`candidate_tree_invalid`, `authorial_schema_invalid`,
`artifact_bound_exceeded`, and `evidence_contract_invalid` belong only to
artifact-contract failure; and `minimum_utility_not_met` belongs only to
minimum-utility failure. The remaining reasons belong only to an executor
failure receipt. Adding a reason is a protocol schema change, not free-form
diagnostic prose.

`work_item_failed` is durable non-run-terminal graph state. `executor_failed` is
durable executor-terminal state. Replay derives graph state in this order:

1. accepted work remains accepted;
2. the executor failure's unresolved trigger item is `failed_executor_contract`;
3. every other unresolved item with the same executor-contract hash is
   `blocked_by_executor_failure` and references the one executor-failure receipt;
4. the unaccepted downstream closure of an item failed or blocked above is
   `blocked_by_failed_dependency`, unless it is already executor-blocked; and
5. every other independent item remains eligible for ordinary planning.

No synthetic per-item receipt is created for executor-blocked items. The planner
excludes all three terminal/blocked categories and continues every independent
ready item, including safe deterministic work, sibling domains, and other
sources. When no safe ready or budget-paused work remains, the controller
appends the one run-terminal `run_failed` summary if any required item is failed,
executor-blocked, or dependency-blocked. Only budget exhaustion pauses an
otherwise dispatchable item as continuable. Raising token or active-time
authorization cannot reopen failed or executor-blocked work, but continuation
can still schedule other unresolved items. Accepted siblings are never
discarded.

Global token and active-time ceilings remain independent hard budget dimensions.
Active time is monotonic time from immediately before executor invocation until
its process or in-process operation has terminated; planning, operator pause,
and idle wall time are excluded. Before lease execution, the planner refuses a
dispatch when either its controller-computed token reservation or its pinned
`max_active_ms_per_dispatch` reservation exceeds remaining authorization.

The appended `dispatch_started` event atomically records attempt authorization,
the execution-input hash, executor-contract hash,
`billable_token_reservation`, and `active_ms_reservation`. The controller starts
the executor with a monotonic deadline equal to that active reservation.
API adapters must abort the client request at the deadline, subprocess adapters
must terminate the subprocess, and in-process executors must expose an
enforceable cooperative deadline and fail closed if they cannot. Active time ends
when the local request/executor has terminated; a remote endpoint may continue
server-side work after disconnect, but the pinned aggregate completion cap still
bounds billable generation. An executor that cannot enforce those local and
token bounds is ineligible rather than merely estimated.

Open dispatches are conservatively charged both reservations. “Billable tokens”
is the pinned normalizer's disjoint sum of provider input, output, cached-input,
and hidden/reasoning token classes. After a trusted exact observation,
accounting charges exact token usage and controller-measured active milliseconds
and releases unused reservations. If a committed capture/observation is absent,
`dispatch_abandoned` permanently charges both full reservations. If provider
token usage is untrusted, accounting charges at least the full token
reservation; active time remains trusted only when the controller observed both
monotonic boundaries. Incomplete telemetry is reported separately. Unknown usage
is never charged as zero. Usage above either reservation is charged at the
greater observed value, records `executor_failed`, and prevents further dispatch
through that executor contract.

For protocol 2.2, `dispatch_started` adds a nonnegative token reservation, a
positive active-time reservation, and the execution-input and executor-contract
hashes above. Provider-backed token reservations must be positive;
deterministic ones are zero. Its `dispatch_observed` execution observation adds
exactly these protocol-2.2 fields to the common timing/exit fields:

```text
execution_capture_hash: string
raw_result_contract_status: "valid" | "invalid" | "not_applicable"
reported_token_usage: nonnegative integer | null
token_usage_status: "trusted_exact" | "unavailable" | "untrusted"
observed_active_ms: nonnegative integer | null
active_usage_status: "trusted_exact" | "unavailable" | "untrusted"
```

The capture hash must resolve to the matching immutable `ExecutionCapture`.
Protocol 2.2 has no free-standing adapter-supplied `result_contract_valid`
boolean; the controller derives provider raw status from persisted stdout bytes
and the pinned parser. Effective provider status may later become
`reconstructed` only through the event defined above. Deterministic execution
requires `not_applicable` and can transition only to deterministic certification
or deterministic failure.
`trusted_exact` requires a value, `unavailable` requires null, and an untrusted
value may be retained for telemetry. Conservative charge is the exact value for
`trusted_exact`, the reservation for `unavailable`, and the greater of
reservation or value for `untrusted`. Any value above its reservation is an
executor-contract breach. Deterministic execution requires reported token usage
zero with `trusted_exact`; provider execution follows its pinned normalizer.
Recovery recomputes reservations from the stored execution input and pinned
contract before applying this reconciliation.
Protocol 2.0/2.1
event and observation payloads retain their existing exact fields.

Budget exhaustion uses conservative charged values for both dimensions rather
than only known observations. Raising a global ceiling authorizes more execution
but does not change context bounds, executor limits, attempt limits, failed-item
state, work-item identity, or artifact identity. The controller remains single-
dispatch in this increment; independent domain nodes make bounded parallel
execution possible later without changing artifact contracts.

## Controller Certification

The L1 certifier is deterministic and controller-owned. It validates:

- the persisted candidate tree, strict authorial payload, and controller-derived
  scope, artifact kind, layer, policy, dependency, and context hashes;
- normalized provider fields against the exact artifact-kind schema, then
  constructs and canonicalizes the complete controller-owned envelope with the
  existing v2 serializer;
- required compact-baseline sections and maximum output size;
- `compact-v1-minimum-utility-v1`;
- canonical, in-bounds evidence references;
- membership of every complete cited line range in the exact context bundle;
- matching excerpt and source-blob hashes in the immutable snapshot;
- same-source ownership of every cited path, plus exact target-domain owned or
  explicitly shared-supporting authorization for domain artifacts;
- source-overview use only of source evidence and same-source projected domain
  evidence, never prior model statements or unprojected artifacts; and
- controller-computed inventory, evidence-pack, and referenced-file coverage;
  required-surface presence; and exact controller-derived depth debt.

Candidates cannot declare coverage. Protocol 2.2 uses these exact controller-
derived schemas:

```text
CountRatio = {
  numerator: nonnegative integer,
  denominator: nonnegative integer
}

CoverageRecord = {
  universe: "direct_read_set" | "projected_domain_read_sets" |
            "combined_evidence_authority",
  inventory_file_count: nonnegative integer,
  selected_file_count: nonnegative integer,
  referenced_file_count: nonnegative integer,
  fully_selected_file_count: nonnegative integer,
  partially_selected_file_count: nonnegative integer,
  omitted_file_count: nonnegative integer,
  omitted_range_count: nonnegative integer,
  selected_over_inventory: CountRatio,
  referenced_over_inventory: CountRatio,
  referenced_over_selected: CountRatio
}

CoverageAssessment = {
  direct: CoverageRecord,
  projected_domains: CoverageRecord | null,
  combined: CoverageRecord
}

RequiredSurfaceRecord = {
  surface: string,
  status: "observed" | "not_established",
  claim_count: nonnegative integer,
  minimum_utility_requirement: "required" | "one_of_entry_or_behavior" |
                               "one_of_boundary_or_relationship" | "none"
}

MinimumUtilityAssessment = {
  rule_id: "compact-v1-minimum-utility-v1",
  passed: boolean,
  diagnostic_codes: [
    "responsibilities_not_observed" | "entry_or_behavior_not_observed" |
    "purpose_not_observed" | "runtime_shape_not_observed" |
    "boundary_or_relationship_not_observed" | "no_regular_file_cited",
    ...
  ]
}
```

An evidence-authority file key is the exact tuple
`(source_id,source_relative_path,authority_kind,origin_domain_key)`. Direct
source or domain read sets use `authority_kind: direct`; source-overview domain
read sets use `authority_kind: domain_projection` and require their stable domain
key. Consequently, one shared supporting path may count once per authorized
domain but cannot collide with direct source authority. Domain artifacts require
null `projected_domains`; every numeric and ratio field in `combined` equals
`direct`, while its universe remains `combined_evidence_authority`. Source
overviews require a non-null projected-domain record, including when its
denominator is zero, and compute `direct` from the complete source inventory/evidence pack,
`projected_domains` from every accepted domain read-set authority key, including
wholly omitted projections, and `combined` from the disjoint union of both key
sets. Selection means the policy selected some or all of that file for the
applicable context; direct evidence-pack selection includes an explicitly
selected empty file, while projected selection requires an excerpt actually
carried into the overview context. Reference means at least one accepted claim
cites the key and therefore always requires a nonempty excerpt. Referenced keys
are a subset of selected keys. Every referenced key is recovered from the exact
descriptor named by an accepted `EvidenceRef.evidence_authority_id`; path-only
inference and counting every authority that happens to share a path are
forbidden.

For a source overview, every integer count in `combined` equals the corresponding
`direct` count plus the non-null `projected_domains` count because their authority
key sets are disjoint; the combined ratios are recomputed from those sums rather
than copied from either record. This applies to inventory, selected, referenced,
fully selected, partially selected, omitted-file, and omitted-range counts.
Projected-domain selection is measured against excerpts actually carried into
the source-overview context, not merely selected by the upstream domain evidence
pack. A wholly omitted domain therefore contributes its complete read-set
inventory and zero selected files here. The separate domain-depth-debt rollup
continues to report upstream domain-pack selection, so the two selection stages
cannot be conflated.

Each ratio repeats the corresponding exact counts. A zero denominator requires
a zero numerator and is rendered as `not_applicable`, never 0% or 100%; no
floating-point percentage enters canonical bytes. Every record requires
`selected_file_count = fully_selected_file_count +
partially_selected_file_count`, `inventory_file_count = selected_file_count +
omitted_file_count`, and `referenced_file_count <= selected_file_count`; the
three ratio fields must repeat exactly those numerators and denominators.
Required-surface records are
sorted in the literal policy surface order. The two `one_of` labels occur only
on their named pair; the boundary pair uses `none` when the source has at most
one domain. A passed assessment requires an empty diagnostic array; a failed one
requires the exact unique applicable codes in the declaration order above. This
reports selected/inventory,
referenced/inventory, referenced/selected, partial selection, omitted files and
ranges without inferring line, behavior, or semantic completeness from citation
count. Referencing one excerpt from every selected file therefore cannot hide
files omitted by the bounded evidence pack or domain projection.

Protocol 2.2 certification and candidate provenance are separate exact objects:

```text
CertificationKeyV2 = {
  identity_schema_version: 2,
  artifact_hash: string,
  artifact_key: ArtifactKey,
  verifier_id: string,
  verifier_version: string,
  verifier_implementation_digest: string,
  scoped_content_id: string | null,
  audit_epoch_id: string | null
}

CertificationAssessmentV2 = CompactCertificationAssessmentV2 |
                            DeterministicCertificationAssessmentV2

CompactCertificationAssessmentV2 = {
  assessment_kind: "compact_baseline",
  coverage: CoverageAssessment,
  depth_debt: DepthDebt,
  required_surfaces: [RequiredSurfaceRecord, ...],
  minimum_utility: MinimumUtilityAssessment,
  normalized_diagnostics: [nonempty normalized string, ...],
  semantic_status: "unaudited"
}

DeterministicCertificationAssessmentV2 = {
  assessment_kind: "deterministic_artifact",
  artifact_kind: string,
  canonical_schema_valid: boolean,
  dependency_closure_valid: boolean,
  policy_conformance_valid: boolean,
  depth_debt: DepthDebt | null,
  normalized_diagnostics: [nonempty normalized string, ...],
  semantic_status: "not_applicable"
}

CertificationReceiptV2 = {
  schema_version: 2,
  certification_key: CertificationKeyV2,
  verdict: "accepted" | "rejected",
  assessment: CertificationAssessmentV2
}

CandidateAssessmentReceiptV1 = {
  schema_version: 1,
  candidate_id: string,
  work_item_id: string,
  execution_capture_hash: string,
  normalized_authorial_payload_hash: string | null,
  artifact_hash: string | null,
  certification_receipt_id: string | null,
  outcome: "certified" | "rejected_before_artifact" |
           "rejected_after_artifact",
  normalized_diagnostics: [nonempty normalized string, ...]
}

ArtifactAcceptanceReceiptV2 = {
  schema_version: 2,
  artifact_key: ArtifactKey,
  artifact_hash: string,
  certification_receipt_id: string
}
```

The certification key's artifact key must hash to the artifact identity, its
verifier digest must match the installed canonical verifier module closure, and
its scoped content ID must exactly equal the artifact scope value. The certification
receipt contains no candidate ID, work-item ID, timestamp, result-reconstruction
flag, provider metadata, or execution observation. Its content digest is the
`certification_receipt_id`, and one key admits exactly one byte-identical receipt.
EGR-165 requires a null audit epoch; EGR-167 owns non-null audit overlays. The
ledger rejects a different assessment or verdict for that key.

Domain baselines and source overviews require the compact assessment. Inventory,
partition, evidence-pack, context-bundle, and source-root artifacts require the
deterministic assessment; its artifact kind must match the key, its debt is
required exactly for evidence packs and context bundles, and is otherwise null.
An accepted deterministic assessment requires all three validation booleans true
and an empty diagnostic array; a rejected one requires at least one false boolean
and one or more diagnostics. This keeps one certification envelope across the
protocol without pretending deterministic objects have model-content coverage or
semantic status. A captured deterministic execution with no object produces
`deterministic_execution_failed`; a rejected deterministic certification is
persisted for diagnostics and then produces `deterministic_artifact_invalid`.
Both use executor-failure authority and never create candidate assessment or
artifact acceptance.

Candidate-specific data lives only in the candidate-assessment receipt and event
provenance. `rejected_before_artifact` requires null artifact and certification
fields; `rejected_after_artifact` requires both and points to a rejected
certification; `certified` requires both and points to an accepted certification.
Any non-null `normalized_authorial_payload_hash` resolves to the exact canonical
normalized payload object persisted before assessment; null is permitted only
when strict parsing or normalization could not produce that object.
The controller persists any certification receipt first, then the candidate-
assessment receipt, then appends `candidate_certified` or `candidate_rejected`
with the applicable IDs. The protocol-2.2 ledger retains record type
`certification`; its payload contains exactly `{receipt:
CertificationReceiptV2, work_item: WorkItemV2}` so verifier/executor/goal
authority remains bound without entering the deterministic receipt identity.
The WorkItem output key and verifier fields must byte-match the certification
key. It adds record type `candidate_assessment` containing exactly
`CandidateAssessmentReceiptV1`. The candidate-assessment ID is its complete
content digest. Diagnostics in both objects follow the same sorted, unique,
1,024-byte normalization used by failure receipts. Accepted certification and a
certified candidate use an empty array; every rejected receipt requires at least
one diagnostic.

The protocol-2.2 ledger retains record type `artifact`, but its payload decoder
is selected by the immutable engine protocol. For protocol 2.2 it contains
exactly `ArtifactAcceptanceReceiptV2`; it never decodes or infers the legacy
candidate-, work-item-, or timestamp-bearing `ArtifactReceipt`. Its artifact key
and hash byte-match the accepted certification key, and its certification ID
resolves to that receipt. The acceptance-receipt ID is the digest of these exact
bytes. One ArtifactKey admits exactly one byte-identical artifact-acceptance
receipt in a run. Candidate choice and acceptance time therefore cannot create a
conflicting artifact authority, and a deterministic artifact needs no invented
candidate. For provider work, the controller fsyncs certification and candidate-
assessment receipts, appends the matching candidate outcome, fsyncs the artifact-
acceptance receipt, and only then appends `artifact_accepted`. For deterministic
work it fsyncs certification and artifact-acceptance receipts in that order, then
appends `artifact_accepted`. No event may cite a later ledger record.

Protocol-2.2 candidate and acceptance event payloads are closed objects:

```text
candidate_certified = {
  work_item_id: string,
  candidate_id: string,
  candidate_assessment_id: string,
  certification_receipt_id: string
}

candidate_rejected = {
  work_item_id: string,
  candidate_id: string,
  candidate_assessment_id: string,
  certification_receipt_id: string | null
}

artifact_accepted = {
  work_item_id: string,
  artifact_key_id: string,
  artifact_hash: string,
  artifact_acceptance_receipt_id: string,
  certification_receipt_id: string,
  candidate_assessment_id: string | null
}
```

Provider L1 acceptance requires a certified candidate-assessment ID whose
artifact and certification fields match the other event fields. Deterministic
acceptance requires null candidate assessment and an accepted deterministic
certification. In both cases the event's artifact fields byte-match the
preceding acceptance receipt. A provider rejection's nullable certification ID
follows the candidate-assessment outcome exactly. A crash after any receipt but
before its event is recovered by validating the immutable object, candidate,
and capture as applicable and appending the one idempotent matching event;
conflicting or unjustified orphan authority fails closed.

Multiple candidates that normalize to the same
artifact reuse the same deterministic certification receipt while retaining
distinct candidate-assessment provenance. Result reconstruction remains only in
execution events. Protocol 2.0/2.1 keys, receipts, ledger uniqueness, and
canonical schemas remain unchanged.

The certifier does not judge whether prose correctly interprets behavior. Every
accepted provider-authored baseline certification therefore records:

```text
semantic_status: unaudited
```

EGR-167 may later add a separately keyed semantic-audit overlay and promote the
audited outcome without regenerating unchanged L1 bytes.

## Materialization

Artifact objects and receipts remain authoritative. After acceptance, the
controller atomically materializes the verified object by the filesystem-safe
hex suffix of its artifact hash:

```text
runs/<run-id>/v2/materialized/L1/
  sources/<source-id>/
    overview/<sha256-hex>/{baseline.json,baseline.md}
    domains/<domain-id>/<sha256-hex>/{baseline.json,baseline.md}
    root/<sha256-hex>.json
```

Materialized paths are immutable projections, not authority. Recovery verifies
their contents against the object store. A missing projection is rebuilt. An
altered or unsafe projection is atomically moved to a run-local quarantine path
without following links, the quarantine move is reported in status, and the
verified object is rematerialized through a no-clobber atomic publish.
Unexpected symlinks, traversal, special files, quarantine failure, and
content/hash mismatches fail closed before provider dispatch. Quarantined bytes
remain recoverable and are never treated as authority.

EGR-165 writes nothing below workspace `re/`. Workspace synthesis, tracked
publication, and a canonical workspace generation remain EGR-168 concerns.

## Status and Terminal Semantics

Human and JSON status report:

- accepted and required L0 inventory/evidence-pack, deterministic L1 context,
  provider L1 baseline, and source-root counts;
- per-source accepted and required domain counts;
- direct, projected-domain, and combined selected/inventory,
  referenced/inventory, and referenced/selected rational file coverage; complete
  source/domain/projection depth debt; required-surface presence; and minimum-
  utility outcome;
- per-item context bytes and conservative input-token estimate;
- run token and active-time authorization, current charged usage, open
  reservations, trusted observed usage, and unknown-usage dispatch counts
  without reporting unknown as exact zero;
- count of complete and terminal-tail execution captures, completed staging
  commits, indeterminate `dispatch_abandoned` attempts, incomplete staging
  telemetry, and result contracts reconstructed from valid candidates;
- current, budget-paused, failed, executor-blocked, and dependency-blocked
  scoped work-item identities, with accepted siblings reported separately;
- normalized result-contract, artifact-contract, minimum-utility, executor-
  contract, indeterminate-execution, or budget reason, with item- or executor-
  failure-receipt ID in JSON status;
- operational `pinned_authority_unavailable` state with each expected and
  installed/missing implementation digest, without mislabeling it a run failure;
- exact accepted source-root hashes and materialized paths;
- `semantic audit: not run`; and
- `workspace synthesis: not run`.

When all requested L0 and L1 nodes are accepted, including every minimum-utility
gate, the final banner is:

```text
L1 COMPACT BASELINE COMPLETE
```

It must also state that semantic audit, workspace synthesis, selective
deepening, and exhaustive RE were not performed. Neither status nor events may
label this outcome `full RE complete`, `full quality`, or an equivalent claim.

An unresolved run whose exact pinned implementation authority is unavailable
prints no terminal event and ends a continuation command with:

```text
L1 COMPACT BASELINE UNAVAILABLE — PINNED AUTHORITY REQUIRED
```

It names the exact executor/renderer/tokenizer/calculator/normalizer/agent/schema
or verifier mismatch and instructs the operator to restore the pinned digest.
Continuation after restoration resumes the unchanged run; changing to a new
implementation requires a new run.

A budget-paused run ends with:

```text
L1 COMPACT BASELINE PAUSED — BUDGET AUTHORIZATION REQUIRED
```

It names the next scoped item and both required reservations and is continuable
after authorization. If failed or executor-blocked items already exist while
other work is budget-paused, the same banner also states that those items remain
terminal/blocked after continuation.

Only after the planner reaches a fixed point with failed, executor-blocked, or
dependency-blocked required work and no independent ready or budget-paused item
does it append `run_failed` and print:

```text
L1 COMPACT BASELINE INCOMPLETE — TERMINAL WORK-ITEM FAILURES
```

It reports accepted/required item, domain, source-root, failed, executor-blocked,
and dependency-blocked counts; names every failed/blocked item and normalized
reason; and distinguishes item artifact/utility failure from executor safety
failure and its derived fan-out. Increasing the budget or repeating `continue`
cannot reopen failed or executor-blocked items. The operator must correct the
provider, configuration, context policy, or implementation and start a new run.
A source root cannot be assembled until its overview and every required domain
baseline are accepted. Accepted siblings and independently completed source
roots remain authoritative in either incomplete state and are never described
as a complete run.

## Recovery and Compatibility

Recovery selects the graph builder and identity decoder from the immutable
engine protocol. For protocol 2.2 it reconstructs the exact graph from:

- the validated composite source snapshot;
- the pinned workspace partition catalog and independently hashed source/domain
  descriptors;
- requested goals;
- the artifact-policy catalog; and
- executor contracts.

Recovery then validates and replays the event log, ledger, candidate state, and
materialized projection. It also reconstructs and verifies evidence packs,
context-bundle hashes, authorial normalization, execution-input objects,
provider-request envelopes, execution-capture commits and stdout blobs,
abandoned-dispatch transitions, reconstructed-result transitions, deterministic
artifact results, certifications, candidate assessments, artifact-acceptance,
item-failure, and executor-failure receipts, shared-retry consumption, exact
failed/executor-blocked/dependency-blocked closure, open token and active-time
reservations, trusted observations, and conservative charged usage. It
loads every prepared or open request from its immutable execution-input and
provider-envelope objects and recomputes both reservations from the immutable
executor contract; it never re-renders with current agent prose. A mismatch
between reconstructed templates, stored envelopes, renderer/agent/schema
digests, calculators, reservations, capture commits, and pinned inputs fails
before provider execution. Replay never converts `work_item_failed`,
`executor_failed`, or their derived blocked closure into semantic repair, a
fresh attempt, or a budget pause; never reissues a started dispatch; never reruns
a provider when a valid persisted candidate can reconstruct the result contract;
and never converts unknown usage into zero.

Protocol 2.0 and 2.1 recovery continues to construct the legacy deterministic
L0 graph and accepts only legacy identity records. Protocol 2.2 accepts only
scoped identity records. No protocol reads another protocol's records as
current authority.

## Verification Strategy

Implementation follows test-driven development. The acceptance matrix covers:

1. Canonical protocol 2.0/2.1 serialization and identity remain byte-for-byte
   stable after protocol 2.2 support is added.
2. Protocol 2.2 rejects missing, unsafe, duplicate, or contradictory source and
   domain scopes.
3. Domain content identity changes for a content-only edit because every owned
   and supporting path/mode/content hash is included; its partition identity
   remains unchanged. The partition-only source artifact and
   `source_partition_id` also remain byte-for-byte unchanged.
4. Full, untruncated stable domain-key digests remain unchanged when presentation
   IDs are renumbered and cannot collide through display-prefix truncation.
5. `layer_policy_hash` changes when any canonical content-contract field changes,
   even if its human-facing version label is reused.
6. Changing `compact-v1` to a different L1 policy changes L1 keys and roots but
   leaves every existing L0 key, including `evidence-pack-v1`, unchanged. A
   higher-detail selection is represented by a higher-layer context artifact,
   never a competing policy-specific L0 evidence pack.
7. Changing one sibling source leaves all scoped keys for untouched sources
   unchanged; changing one domain leaves unrelated domain inventory and
   baseline keys unchanged.
8. Inserting a sibling domain may renumber presentation domain IDs but leaves
   stable keys and artifacts for unchanged domain roots unchanged.
9. A content-only change to a shared supporting artifact invalidates exactly the
   content-bearing domain read sets that explicitly contain it and does not
   change partition-only bytes or IDs.
10. Path membership, source/domain supporting assignment, ownership, or
    presentation assignment changes the exact relevant domain and source
    partition identities. No changed source-partition bytes can retain one
    `source_partition_id`.
11. Partition generation and graph reconstruction are deterministic across
    input ordering and process restart.
12. RunManifestV2, BudgetPolicyV2, WorkTemplateV2, WorkItemV2, every catalog,
    provider-request envelope, execution input/capture commit, persisted
    candidate, partition,
    inventory, evidence-pack, context-bundle, receipt, event, and source-root
    schema rejects unknown fields and noncanonical order; round-trip canonical
    bytes and hashes are stable across restart. Schema-1 work and receipt objects
    are never inferred into protocol 2.2.
13. Evidence-pack selection is byte-stable across input ordering, process
    restart, provider, model, and exact-tokenizer availability. It never follows
    links, respects provider-neutral canonical byte/token caps for pathological
    long lines, and reports non-UTF-8, NUL, non-regular, partial, and omitted debt.
14. CRLF normalization, raw excerpt hashing, LF-based original line numbering,
    final unterminated lines, and strict UTF-8 eligibility follow the literal
    byte rules and reconstruct exactly from the pinned source blob.
15. Each domain context-bundle closure contains only its exact accepted domain
    inventory and evidence pack, and the baseline directly depends on that
    context hash. Each source-overview context depends on its bounded source pack
    and accepted domain hashes, and never contains the full source tree or
    concatenated complete domain artifacts.
16. Source-overview projections preserve accepted semantic claim order, carry
    complete original evidence and full baseline depth debt for every retained
    claim, and report exact per-domain, whole-domain, rollup, and omitted-claim
    debt rather than opaque hashes or lexical selection.
17. Each source root depends on the exact overview and domain artifact hashes but
    contains no certification receipt IDs. Re-certifying unchanged artifacts
    reuses one byte-identical deterministic certification receipt while distinct
    candidate-assessment events preserve provenance; one timestamp-free
    `ArtifactAcceptanceReceiptV2` remains stable and root key and bytes remain
    unchanged.
18. One active graph has one output per `(scope,artifact_kind,layer)` while old
    differently keyed policy objects may coexist outside that graph without
    becoming competing authority.
19. Provider, model, and run resource-limit changes between runs do not alter
    artifact keys; no test claims cross-run adoption before EGR-166. Provider,
    adapter implementation, endpoint/API/routing authority, model revision,
    reasoning, sampling, agent contract, response schema, request renderer,
    tokenizer, calculator, normalizer, verifier implementation, or per-dispatch
    limit drift inside one run produces non-mutating
    `pinned_authority_unavailable` before dispatch or certification, as
    applicable; restoring the exact digest resumes the same state.
20. Baseline run creation resolves and pins the configured L1 executor before
    manifest or active-pointer mutation; recovery rejects missing, incompatible,
    unbounded, revision-unresolved, or implementation-digest-mismatched
    executors, transports, renderers, agents, response schemas, and calculators.
    EGR-165's built-in bounded API adapter proves one-call, no-tool, exact stored-
    envelope replay, hard aggregate-completion, revision, and deadline
    enforcement. General agentic CLI adapters fail preflight with the exact
    missing capability. An inventory-only run requires no unused provider
    contract.
21. The default v2 goal plans the complete baseline closure, inventory-only
    remains deterministic, and shadow mode performs zero provider dispatches
    while reporting per-item input estimates and controller-computed whole-run
    maximum token and active-time reservations for initial and retry paths.
22. Context construction rejects canonical byte, provider-neutral conservative-
    token, provider context-window, billable-reservation, and active-reservation
    overflow before dispatch. Exact execution tokenization covers system/user
    messages, response schema, provider framing, and reasoning input from the
    stored envelope; it can reject a request but cannot alter deterministic
    context bytes.
23. The authorial candidate schema accepts only `schema_version`, the exact
    target-specific surface map, and unknowns; it rejects empty normalized
    statements/questions, reversed ranges, mixed surface maps, controller-owned
    identity/debt fields, missing `baseline.json`, symlinks, special files, and
    extraneous candidate entries.
24. Strict JSON parsing rejects duplicate keys, non-finite values, unknown fields,
    and oversize raw or canonical content. Controller normalization makes
    whitespace/object-key, NFC, newline, and authority-qualified evidence-order
    variants canonical without a retry, preserves within-surface semantic claim
    order, and rejects duplicates that collide after normalization.
25. The controller injects the exact WorkItem identity, context dependency, and
    depth debt. A provider cannot change accepted artifact identity by echoing or
    omitting metadata because candidate schema contains no such fields.
26. A valid one-file authorial candidate with an absent or malformed trailing
    result reconstructs a durable result event and consumes no retry, including
    across crash/recovery. A malformed result without such a candidate consumes
    `result_contract_retry`; a present/reconstructed result with an invalid
    artifact consumes `artifact_contract_retry`. Reconstruction clears result-
    retry eligibility before certification.
27. The minimum-utility gate rejects an all-`not_established` domain or source,
    enforces the exact observed surfaces and cited-file minimums, and prevents a
    utility failure from producing a complete banner.
28. Certification accepts a domain's owned and explicitly shared-supporting
    evidence and a source overview's same-source domain-projection evidence. It
    rejects sibling-source evidence, unprojected prior artifacts, sibling-owned
    paths not declared shared, traversal, nonexistent lines, and mismatched raw
    excerpt/blob hashes. A path appearing as direct evidence and in multiple
    domain projections remains independently citable through exact evidence-
    authority IDs; path-only or wrong-domain references are rejected.
29. Exact rational coverage records distinguish direct, projected-domain, and
    combined evidence-authority universes plus selected/inventory,
    referenced/inventory, and referenced/selected files. Zero denominators render
    not-applicable, shared read-set entries cannot collide, and omitted evidence
    cannot appear complete.
30. Deterministic Markdown rendering is byte-stable, bounded, and derived only
    from accepted canonical JSON.
31. No work item can receive both retry kinds or more than one shared retry. An
    exhausted retry first appends one exact `WorkItemFailureReceipt`, then durable
    `work_item_failed` with the matching result, artifact, minimum-utility, or
    indeterminate-execution failure class, never semantic repair or budget-
    continuable state. Recovery completes a valid orphan receipt and rejects a
    conflicting one.
32. A work-item failure blocks only its downstream dependency closure. The
    planner completes independent sibling domains and sources, and appends
    run-level `run_failed` only after no safe ready or budget-paused work remains.
33. An `ExecutorFailureReceiptV1` and `executor_failed` event mark the trigger
    failed, derive `blocked_by_executor_failure` for every other unresolved item
    bound to that exact contract, and derive downstream dependency blocking. They
    leave the breaching candidate unaccepted, preserve accepted artifacts, and
    allow work bound to independent executors to finish with exact status counts.
34. `bounded-dispatch-v1` recomputes the item reservation from the persisted
    canonical `ExecutionInput`, complete `ProviderRequestEnvelopeV1`, provider
    framing bound, and pinned call/aggregate-completion/follow-up ceilings; an
    adapter-supplied different value is rejected. Recovery uses stored envelope
    bytes and produces the same execution-input hash and reservation after
    installed prose or mutable provider defaults change. `bounded-in-process-v1`
    records a zero token reservation and a positive enforceable active-time
    reservation.
35. Dispatch start durably reserves both billable tokens and active milliseconds.
    Exact trusted observations reconcile each reservation; missing or untrusted
    observations charge the applicable full reservation; values above reservation
    produce executor-failure authority. Budget exhaustion never compares only
    known usage.
36. Active-time deadlines terminate provider subprocesses or cooperative in-
    process work at the pinned reservation. Remaining authorization smaller than
    either reservation pauses before lease execution and cannot overshoot by
    starting the work optimistically.
37. Crash/restart before `dispatch_started` may safely start the prepared request.
    After `dispatch_started`, recovery never reissues that dispatch ID. A complete
    ready/committed capture is adopted without a provider call; incomplete
    staging produces one fully charged `dispatch_abandoned`, a new counted retry
    only for provider work when authorized, and otherwise terminal
    execution-indeterminate item failure. Faults at every
    input, reservation, candidate/inventory, stdout/capture-ready/commit, result-
    reconstruction, deterministic-certification, candidate-assessment,
    acceptance/failure-receipt, event, ledger, and materialization boundary replay
    to the state prescribed by the four-case recovery table.
38. Corrupt materialization is quarantined without following links and rebuilt
    from verified object authority before any provider dispatch.
39. Status and final banners distinguish complete, budget-continuable pause,
    pinned-authority unavailable, failed, executor-blocked, dependency-blocked,
    indeterminate abandoned dispatches, accepted siblings, semantic audit,
    synthesis, selective depth, and full-quality completion, and report both
    budget dimensions plus reconstructed results.
40. A clean multi-source fixture completes with independently accepted, minimum-
    utility domain artifacts and exact source roots while writing nothing below
    workspace `re/`.
41. A fixture with one permanently invalid domain proves that all independent
    domains and sources finish, its dependent overview/root remain blocked, and
    the final banner reports exact accepted/failed/blocked counts.
42. A representative large-source fixture with oversized, binary, non-UTF-8,
    CRLF, and pathological long-line files proves deterministic debt and the
    per-dispatch input ceiling and shadow maximum-cost calculation; no successful
    or failed work item exceeds two provider calls.
43. The established v1-isolation suite proves that v1 dispatch, continuation,
    publication, and status remain unchanged.
44. Every `policy_parameters` branch rejects unknown/missing fields, wrong
    literals, noncanonical classifier order, and mutated classifier patterns;
    every accepted policy change alters `layer_policy_hash`.
45. Complete and terminal-tail stdout captures replay result parsing from stored
    bytes. A complete staging-ready capture can finish its no-clobber commit; a
    stdout digest without its blob, a mismatched complete digest, an ambiguous
    truncated terminal block, or incomplete staging cannot become observation
    authority and never causes re-execution of its dispatch ID.
46. Two candidates normalizing to one artifact share one deterministic
    `CertificationReceiptV2`, retain distinct `CandidateAssessmentReceiptV1`
    provenance, use one candidate-free/timestamp-free
    `ArtifactAcceptanceReceiptV2`, and cannot conflict through candidate IDs or
    timestamps.

## Completion Criteria

EGR-165 is complete only when the shipped `bounded-api-baseline-v1` adapter passes
its hard-limit/revision conformance suite and a live protocol 2.2 fixture run
produces controller-certified, minimum-utility L1 source and domain artifacts,
exact source roots, recoverable run-local materialization, and an unambiguous
compact-baseline banner. The implemented schemas must make every deterministic
catalog, partition-only projection, policy object, evidence pack, context bundle,
certification assessment, and source root byte-reproducible. Graph fixtures must
prove that changing provider/tokenizer cannot change deterministic bytes,
changing only the L1 content policy preserves identical L0 keys, support-
assignment changes re-key partition bytes, content-only changes do not re-key
partition-only bytes, and sibling source/domain changes preserve unaffected
scoped keys.

A representative large-source fixture must additionally prove that no complete
provider-request envelope exceeds its pinned byte, conservative-token, provider-
context, billable-token, or active-time reservation ceiling; shadow output
predicts both maximum authorized budget dimensions; unknown observations charge
their reservations; valid committed candidates survive malformed result prose
without a second provider call; stored execution input/envelope survives
installed-agent and mutable-default changes; and every work item terminates after
at most one initial call plus one shared retry. A budget pause must resume only
the unresolved delta. Failed and executor-blocked items must remain non-repairable
by a budget increase while independent executors continue to a fixed point, with
exact accepted/failed/executor-blocked/dependency-blocked status. Evidence
fixtures must prove authority-qualified owned/shared/domain-projection scope,
including duplicate physical paths, transparent source and domain depth-debt
rollups, exact rational coverage, and that empty normalized or otherwise
structurally empty output cannot be called complete. Crash fixtures must prove
capture-commit adoption, conservative abandonment without reissuing a dispatch,
byte-authoritative stdout reconstruction, deterministic certification with
separate candidate provenance, stable artifact-acceptance authority, and
receipt-before-event recovery. Operational adoption of matching keys remains an
EGR-166 completion criterion.

EGR-165 completion does not make RE v2 the default and does not satisfy the
full-quality cutover condition. EGR-166 through EGR-170 remain required.
