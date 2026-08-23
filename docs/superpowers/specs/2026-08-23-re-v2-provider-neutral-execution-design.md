# RE v2 Provider-Neutral Execution Design

**Date:** 2026-08-23
**Status:** Approved architecture; written-spec review pending
**Relationship:** Corrects the API-only execution eligibility introduced by
`2026-08-21-re-v2-layered-baseline-design.md`

## Purpose

RE v2 must execute with every provider supported by normal Echelon workflows.
The configured provider is user authority: RE may not require an OpenAI API key
when the workspace selects Codex, silently replace Claude with another backend,
or fall back to RE v1 because one provider lacks a transport control.

Protocol 2.2 incorrectly made the strongest guarantees of one API transport an
eligibility condition for compact-baseline generation. In particular, it
required a hard provider-side completion-token ceiling, exactly one observable
model request, disabled tools, and an exact resolved model revision. Current
agentic CLI transports cannot all prove those properties even though they can
produce and certify the same RE artifact.

This design separates semantic authority from execution assurance:

- Every provider receives the same immutable snapshot-derived evidence,
  produces the same authorial schema, and passes the same controller-owned
  certification and quality gates.
- Echelon uses the strongest execution controls the selected provider exposes.
  Missing transport controls reduce the declared execution-assurance class;
  they do not reduce artifact quality or make that provider ineligible.

## Decision

New RE v2 runs use capability-negotiated execution under engine protocol `2.3`.
The controller selects exactly one of these execution classes for each provider
producer and pins it before publishing the run manifest:

1. `strict_bounded`: a provider API or CLI can prove the complete bounded
   one-request contract.
2. `contained_api`: Echelon owns one direct API request, but one or more strict
   metadata or resource guarantees are unavailable.
3. `contained_cli`: Echelon launches one isolated provider CLI process and
   enforces every boundary available outside the provider's opaque internal
   agent loop.

Deterministic controller work remains `bounded_in_process`.

Selection is automatic and stays on the configured provider. Echelon prefers
`strict_bounded`, falls back to the contained class matching the configured
transport when any strict capability is unavailable, and reports the selected
assurance without requiring an opt-in flag. It fails creation only when the
provider cannot satisfy the shared semantic and transport-containment minimum,
not merely because it lacks a hard token cap, exact revision reporting, or a
no-tools switch.

The compact baseline remains preferably tool-free, but the actual invariant is
**snapshot-authoritative and mutation-free**, not universally **tool-free**.

## Options Considered

### Capability-negotiated execution — selected

Use a strict transport where possible and a first-class contained transport
otherwise. Every class feeds one shared artifact parser and certifier.

Benefits:

- preserves provider parity;
- preserves the strongest available cost controls;
- keeps semantic quality independent of transport;
- exposes rather than hides weaker assurance; and
- lets future provider releases upgrade assurance without changing artifact
  identity.

Costs:

- manifests, status, telemetry, and tests must represent different assurance
  classes;
- a dispatch-boundary request/process can overshoot its reservation before
  Echelon regains control; and
- exact remote model revision and internal tool/model-call activity can remain
  unobservable.

### One least-common-denominator CLI contract — rejected

Run every provider through an agentic CLI and advertise only the controls common
to all providers. This is superficially uniform but throws away hard API limits
where they are available and makes cost predictability worse for no semantic
benefit.

### API-only execution or silent provider replacement — rejected

Requiring an OpenAI-compatible API preserves protocol 2.2's strongest envelope,
but violates Echelon's provider-neutral behavior. Silently routing a Codex or
Claude workspace through a different API also changes user-selected cost,
credentials, privacy boundaries, and model behavior.

## Protocol Boundary and Compatibility

Protocol `2.2` and run-manifest schema 2 are immutable. Existing protocol-2.2
runs continue with their pinned API-only executor rules and are never migrated
or reinterpreted in place.

After this change:

- `echelon re run --engine v2` creates protocol-2.3 runs;
- inventory and baseline goals share the protocol-2.3 manifest boundary;
- `echelon re continue` dispatches from the immutable protocol recorded by the
  existing run;
- status and recovery continue to understand protocols 2.0, 2.1, and 2.2; and
- a provider rejected before a protocol-2.2 manifest was created can simply
  start a new protocol-2.3 run.

Protocol 2.3 introduces run-manifest schema 3 and executor-contract catalog
schema 2. The manifest retains the protocol-2.2 source snapshot, partition,
artifact-policy, requested-goal, and budget authorities. Its changed schema
exists solely so the closed manifest can reference the new closed executor
catalog without weakening the meaning of schema 2.

Artifact keys do not include provider, transport, assurance class, model,
budget, or tool-control details. Accepted content is therefore semantically
identical across execution classes. Execution contracts, captures, and
assurance observations preserve the provenance needed to distinguish how those
bytes were produced.

Protocol 2.3 deliberately reuses identity schema 2, the `compact-v1` artifact
policy, and the `compact-baseline-v1` producer protocol. Work-template and
work-item identities change because they pin a different executor contract, but
their output `ArtifactKey` remains identical when scope, content, partition,
policy, producer, and dependencies are identical. The protocol amendment must
not manufacture a new semantic layer merely because transport assurance changed.

## Shared Semantic Contract

Every provider-backed protocol-2.3 work item uses the same semantic path:

1. The controller constructs and persists the canonical context bundle from the
   pinned clean-Git composite snapshot and accepted dependencies.
2. The provider receives the neutral `echelon.re-baseliner` contract, target
   scope, authorial JSON schema, content policy, and that context bundle.
3. Transport-specific capture persists the provider-authored candidate bytes
   before interpreting them.
4. The shared strict parser rejects unknown fields, duplicate keys, invalid
   Unicode, non-finite numbers, extra files, and oversize output.
5. The controller injects identity and debt metadata and applies the same
   structural, evidence-scope, minimum-utility, and size certification.
6. Only a controller-certified candidate can become an accepted artifact.

No assurance class may:

- use the live mutable source checkout as evidence authority;
- allow provider prose to declare coverage, identity, certification, or run
  state;
- weaken evidence citation, minimum utility, output schema, or artifact size;
- convert invalid provider output through heuristic Markdown/prose extraction;
  or
- describe a semantically partial artifact as complete.

An artifact statement is authoritative only when its evidence reference resolves
inside the pinned context bundle and ultimately to the pinned snapshot. External
model knowledge or information observed by a provider-native tool cannot become
accepted source evidence.

## Capability Negotiation

Every registered provider adapter that supports normal Echelon agent execution
must expose a deterministic RE capability inspection. The inspection is local
and non-billable. It resolves the configured provider, executable or endpoint,
adapter version, requested model, effective non-secret settings, available
sandbox and structured-output controls, usage reporting, and deadline support.

The controller converts that inspection into a closed
`ExecutionAssuranceContractV1` before manifest publication:

```text
ExecutionAssuranceContractV1 = {
  assurance_class: "strict_bounded" | "contained_api" |
                   "contained_cli" | "bounded_in_process",
  transport: "api" | "cli" | "in_process",
  request_boundary: "hard_one_request" | "one_echelon_process" |
                    "not_applicable",
  token_enforcement: "hard_per_request" | "dispatch_boundary" |
                     "not_applicable",
  tool_control: "disabled" | "snapshot_read_only" |
                "sandbox_contained" | "isolated_root" |
                "not_applicable",
  source_authority: "pinned_context_bundle" |
                    "pinned_snapshot_or_dependencies" |
                    "not_applicable",
  workspace_write_control: "denied" | "isolated_candidate_only" |
                           "not_applicable",
  model_revision_assurance: "exact" | "requested_only" |
                            "not_applicable",
  usage_assurance: "trusted_when_reported" | "untrusted_or_unavailable" |
                   "not_applicable",
  hard_deadline: boolean,
  hard_capture_byte_limit: boolean
}
```

Provider work requires `source_authority: pinned_context_bundle`.
Deterministic work uses `pinned_snapshot_or_dependencies` when it reads run
authority and `not_applicable` only when it has no source/dependency input. Its
request, token, tool, model, and usage fields are `not_applicable`; no executor
may select convenient nulls independently.

The complete executor entry also pins the provider ID, adapter ID/version and
implementation digest, executable/API authority, request renderer, response
schema, requested model and reasoning settings, capability-inspection digest,
reservation calculator, usage normalizer, subprocess environment policy, and
all applicable limits.

Capability selection follows this exact order:

1. Select `strict_bounded` when all strict requirements are proven.
2. Otherwise select `contained_api` for a direct API adapter that can persist one
   immutable request, apply a controller deadline, and capture one candidate,
   even when exact revision, hard token, context, schema, or usage authority is
   incomplete.
3. Otherwise select `contained_cli` when the adapter can run non-interactively,
   accept Echelon-owned input, expose an isolated execution root, preserve one
   candidate-output boundary, stream or retain output for capture, and obey
   controller termination.
4. Fail before manifest publication only when the configured adapter cannot
   satisfy those contained-CLI minimums.

The reason for every strict-to-contained downgrade is retained in the executor
catalog and printed by shadow/status. There is no provider allowlist and no
special Codex-only branch: Claude, Codex, Copilot, OpenCode,
OpenAI-compatible, and future registered providers use the same negotiation.

## Strict-Bounded Execution

`strict_bounded` preserves the existing `bounded-api-baseline-v1` semantics and
also permits a future CLI that can prove them. It requires:

- one provider model request;
- no provider or Echelon follow-up within the attempt;
- tools disabled;
- a hard aggregate completion/reasoning-token ceiling;
- a known context-window check;
- exact model revision authority;
- a hard controller deadline;
- exact immutable request rendering; and
- trustworthy usage normalization or conservative full-reservation charging.

The existing protocol-2.2 API adapter can be registered under protocol 2.3
without changing its wire behavior. Protocol-2.3 execution/capture schemas add
assurance provenance but the provider-authored payload and shared certification
remain unchanged.

## Contained-API Execution

`contained_api` preserves the controller-owned, non-agentic API request path
when the endpoint cannot prove every `strict_bounded` property. It still issues
one immutable Echelon request, supplies no Echelon follow-up, applies the
controller deadline and capture bounds, and feeds the shared candidate parser.

Its detailed assurance contract records each missing property independently.
For example, an endpoint may have `request_boundary: hard_one_request`,
`tool_control: disabled`, and `token_enforcement: hard_per_request` while using
`model_revision_assurance: requested_only`; another may lack the hard completion
cap and therefore use `token_enforcement: dispatch_boundary`. The summary class
must not erase stronger individual controls that are actually available.

## Contained-CLI Execution

`contained_cli` is a supported production executor, not an escape hatch or a
legacy fallback. One logical attempt launches exactly one Echelon-owned CLI
process. Echelon never sends an interactive follow-up to that process. A retry
starts a new dispatch and consumes the existing shared retry budget.

Before launch, the adapter creates a fresh execution root containing only:

- the immutable rendered request or provider-native command input;
- the canonical context bundle, when the provider requires a file rather than
  embedded content;
- the strict response schema, when supported; and
- an empty isolated candidate-output location, when file capture is used.

The live source checkout, run ledger, object store, materialized artifacts,
active-run pointer, and sibling work are not placed in that execution root. The
prompt uses logical snapshot paths, never a host path that invites discovery of
the original checkout.

The adapter applies the strongest available provider-native and host controls:

1. Disable all tools when the CLI exposes a reliable no-tools mode.
2. Otherwise permit only an Echelon-owned read-only snapshot/context tool and
   isolated candidate write, if the CLI supports a closed allowlist.
3. Otherwise run provider-native tools inside the adapter's tested sandbox with
   no live source checkout and no writable workspace authority.
4. If the CLI exposes no technical sandbox/allowlist, run it from the same fresh
   isolated root without any unsafe permission-bypass option, omit every source
   and run-authority host path from its input, and declare `isolated_root` rather
   than claiming technical tool confinement.

Provider transport network access needed to call the selected model remains
available. Web-search, arbitrary external-data, and mutable-workspace tools are
disabled or sandbox-denied whenever the provider exposes such a control. Under
`isolated_root`, the neutral contract confines work to disposable input/output,
but provider-native tools may still operate because Echelon has no technical
switch to prevent them. Echelon does not claim enforcement it cannot observe.
Regardless of mode, external information cannot satisfy evidence certification.
An adapter never enables an unsafe/bypass-all-permissions flag for RE.

Observed prohibited tool access is an executor safety failure when it
contradicts a promised `disabled`, `snapshot_read_only`, or
`sandbox_contained` control. Under `isolated_root`, ordinary tool activity is
telemetry rather than failure; an observed attempt to target protected source or
run authority is still a safety failure. Unobservable activity is reported as
unverified, never relabeled as disabled.

The controller always enforces these hard external boundaries:

- active wall-clock deadline and process-tree termination;
- stdout, stderr, event-stream, and candidate byte limits;
- exactly one accepted candidate payload;
- safe regular-file/no-symlink candidate capture;
- no source, run-authority, or materialization write path supplied through the
  declared execution root; and
- no second Echelon dispatch under the same dispatch ID.

The CLI may perform opaque internal model calls before exiting. That fact is not
treated as a semantic failure because the accepted artifact still passes the
shared certifier. It is reflected in request and token assurance.

`isolated_root` is the least-assured but provider-neutral production mode. It
matches the safety level of an ordinary non-bypass Echelon CLI dispatch while
further removing the live checkout from the working directory and source input.
It protects what may become RE semantic authority through immutable inputs,
strict output capture, and certification; it does not claim to be an
operating-system security boundary or to prevent an arbitrary process from
discovering other same-user host paths.

## Candidate Capture and Result Fallback

Provider-native structured output is preferred but is not required for provider
eligibility. Each adapter pins one capture strategy:

- `assistant_content`: persist one final assistant content value as
  `baseline.json`; or
- `isolated_candidate_file`: persist the sole regular `baseline.json` written
  below the isolated candidate directory.

An adapter may use a native JSON Schema/output-schema switch to improve result
reliability. When the provider lacks that feature, the neutral agent contract
requests the same JSON shape and the controller's strict parser remains the
authority. Echelon does not repair fenced JSON, scrape arbitrary transcript
prose, or accept an informal success statement.

`tool_control: disabled` requires `assistant_content`; an executor cannot claim
all tools are disabled while depending on a file-write tool for its result.
`isolated_candidate_file` requires
`workspace_write_control: isolated_candidate_only` and a tool-control mode that
permits that declared write. API execution always uses `assistant_content`.
Schema validation rejects every contradictory combination before manifest
publication.

Missing, ambiguous, truncated, malformed, or extra output follows the existing
result-contract/candidate-contract failure and shared-retry rules. A provider
without native schema enforcement may consume more retries, but it cannot
produce a lower-quality accepted result.

## Immutable CLI Invocation and Recovery

Provider-neutral fallback may not reintroduce mutable CLI defaults at dispatch
or recovery. Before `dispatch_started`, the controller persists one closed
logical invocation envelope:

```text
CliInvocationEnvelopeV1 = {
  schema_version: 1,
  dispatch_id: string,
  work_item_id: string,
  executor_contract_hash: string,
  assurance_contract_hash: string,
  requested_model: string,
  argv_template: [string, ...],
  stdin_blob_hash: string | null,
  execution_files: [{logical_path: string, object_hash: string,
                     access: "read_only" | "candidate_output"}, ...],
  non_secret_environment: [{name: string, value: string}, ...],
  secret_environment_names: [string, ...],
  capture_strategy: "assistant_content" | "isolated_candidate_file",
  active_ms_limit: positive integer,
  capture_byte_limits: {stdout: positive integer, stderr: positive integer,
                        event_stream: positive integer,
                        candidate: positive integer}
}
```

`argv_template` is an argument array, never a shell command. It permits only
closed protocol placeholders for the fresh execution root and declared logical
files. It cannot contain a live source/run path, credential value, shell
expansion, or unresolved provider default. Secret names identify runtime
credential injection without storing values. Arrays and maps are canonical,
sorted where order is not semantic, and schema-validated.

Protocol-2.3 `ExecutionInput` references exactly one API request envelope, CLI
invocation envelope, or deterministic invocation. The referenced envelope and
all input blobs are fsynced before `dispatch_started`. The CLI adapter expands
only the pinned execution-root placeholders and verifies its executable,
renderer, settings, and assurance digests immediately before launch.

Recovery never rebuilds a CLI command from current configuration. Before a
dispatch has started, it may expand the stored logical envelope into a new empty
execution root. After durable `dispatch_started`, it follows the existing
capture-commit/abandonment state table and never reissues that dispatch ID. An
abandoned contained-CLI dispatch charges its full token and active-time
reservations because its internal activity is unknowable.

## Token and Time Accounting

Run-wide token authorization retains one interface across providers. Users do
not need a separate `--allow-best-effort-budget` switch.

For `strict_bounded`, the protocol-2.2 reservation and reconciliation rules
remain: Echelon computes the complete request reservation, the provider enforces
the completion ceiling, and exceeding the reservation is an executor contract
breach.

For any contained transport with
`token_enforcement: dispatch_boundary`, the executor contract pins a positive
conservative `max_billable_tokens_per_dispatch`. Before launch, the ledger
reserves that entire amount and refuses to start when remaining run authorization
is smaller. The reservation is a dispatch-admission bound, not a claim that the
provider enforces an internal token ceiling.

`contained-dispatch-v1` fixes that reservation at 262,144 billable tokens per
dispatch, matching protocol 2.2's existing safety ceiling. It is protocol
authority rather than a mutable adapter estimate. A later configurable or
provider-specific reservation policy requires a newly pinned calculator/version;
continuation may not change it inside an existing run.

The detailed `token_enforcement` field, not the summary assurance class, selects
the reservation calculator. A `contained_api` transport with a proven hard
completion cap uses the strict calculator; only a dispatch-boundary transport
uses `contained-dispatch-v1`.

After capture:

- complete trusted provider usage charges the observed amount and releases the
  unused reservation;
- missing, incomplete, or untrusted usage charges the full reservation;
- trusted usage above the reservation charges the full observed amount, records
  `dispatch_token_overrun`, and prevents another dispatch until the resulting
  run-wide authorization state is resolved; and
- an overrun does not invalidate an otherwise certified artifact, because the
  known inability to hard-cap the transport was already represented by
  `token_enforcement: dispatch_boundary`.

Consequently, a dispatch-boundary transport can exceed a run token authorization
by at most the unpreventable overrun of an already-started request or process.
Status and the final banner must say so explicitly; they may never call this a
hard token ceiling. A contained API that retains a hard provider completion cap
continues to use hard per-request accounting despite its weaker revision or
metadata assurance.

An overrun transitions the run to a continuable
`budget_paused_after_dispatch_overrun` state after the current candidate is
captured and assessed. Continuation may raise the run-wide token authorization;
it cannot erase the charge, change the per-dispatch reservation, or launch more
work while charged usage plus the next reservation exceeds authorization.

Active time is different: Echelon owns the request/process deadline and therefore
enforces the pinned active-time reservation as a hard deadline for every
provider assurance class. Timeout or failed cancellation/process-tree
termination follows executor-safety failure handling and never becomes a
budget-continuable pause.

## Model and Configuration Authority

All provider execution classes pin the requested provider, requested model string,
reasoning/effort settings, adapter implementation, and all observable
non-secret settings before manifest publication.

A CLI adapter must suppress mutable user configuration when the provider offers
an isolation switch. If authentication depends on the provider's user home, the
adapter exposes only the credential/login material required for transport while
passing model, tools, output mode, and other behavior-affecting settings
explicitly. When a behavior-affecting provider configuration file cannot be
suppressed, the adapter snapshots its non-secret canonical bytes into the
executor contract and materializes that pinned copy for every dispatch. An
unhashed mutable user default may never become execution authority.

`strict_bounded` additionally pins and verifies the exact resolved model
revision. A contained transport records an exact revision when the provider
reports one; otherwise it pins the requested model alias and declares
`model_revision_assurance: requested_only`. A remote alias can therefore change
between pending dispatches without Echelon being able to detect it. Existing
accepted artifacts remain immutable, and status exposes the limitation.

Continuation never changes provider, requested model, adapter digest, capture
strategy, or assurance contract. Installation drift makes unresolved execution
`pinned_authority_unavailable`, as in protocol 2.2. Restoring the pinned adapter
resumes the run; choosing another provider or assurance contract requires a new
run.

Credentials and provider-login material remain runtime secrets outside content
identity. A contained CLI execution root exposes only the minimum read-only
credential/config authority needed by that CLI. No transport copies credential
bytes into an immutable request/invocation object, capture, event, or telemetry
record.

## Durable Provenance

Every provider dispatch persists an `ExecutionAssuranceObservationV1` alongside
the execution capture. It records:

- the pinned assurance-contract hash;
- selected execution class and transport;
- which controls were requested and which were observed;
- requested and observed model identifiers when available;
- capture strategy;
- tool activity summary when observable;
- normalized usage status and counts;
- reservation, charge, and any overrun;
- deadline, exit, truncation, and process-termination observations; and
- normalized downgrade or safety-failure reasons.

Observations are execution provenance, not artifact content. They do not enter
the artifact key or provider-authored candidate. Recovery reconstructs charges
and status from persisted observations and never promotes an unobserved control
to a hard guarantee.

Protocol 2.3 introduces `ExecutionCaptureV2`. It adds `cli` to the execution-mode
enum and requires an `assurance_observation_hash` for every provider-backed
capture. The observation contains the execution-input and assurance-contract
hashes but never the capture hash, avoiding a digest cycle. Usage, event-stream,
candidate/stdout, and observation objects are written and fsynced first; the
capture then references them, and the existing no-clobber capture commit makes
that complete closure authoritative. Deterministic captures require a null
assurance-observation hash. Recovery rejects a provider capture whose observation
is missing, noncanonical, hash-mismatched, or inconsistent with the immutable
executor/invocation contract.

## Status, Shadow, and Final Banner

Shadow output reports the selected provider and assurance class before any
billable execution. For a contained transport it prints the reasons strict
execution was unavailable and, when applicable, the worst-case
dispatch-boundary reservation.

`echelon re status` and every terminal banner include an assurance summary such
as:

```text
provider: codex
execution assurance: contained-cli
token enforcement: dispatch-boundary
tool control: sandbox-contained
model revision: requested alias; exact revision unverified
artifact certification: compact-v1 passed
quality scope: L1 compact baseline; semantic audit/synthesis not run
```

For an adapter without a technical tool boundary, the corresponding line is
`tool control: isolated-root; technical tool restriction unverified`. It must
never display `sandbox-contained` merely because the process used a temporary
working directory.

Mixed-executor runs report counts by assurance class and identify any token
overrun or untrusted usage. Semantic completion language remains determined by
accepted artifact coverage and certification, not by execution class. An L1
baseline generated through contained CLI may therefore be
`L1 COMPACT BASELINE COMPLETE`, but status must not describe its resource
controls as strict-bounded.

## Failure Semantics

These conditions remain ordinary provider-result failures eligible for the
pinned shared retry when available:

- missing or malformed final result;
- invalid authorial JSON;
- schema, evidence, utility, or size failure; and
- ambiguous CLI capture.

These conditions are executor-safety failures and fan out only to work pinned to
the same executor contract:

- inability to establish the declared isolated execution root;
- observed source/run-authority mutation attempt;
- prohibited tool or network activity that the adapter promised to deny;
- active-time/process-tree termination breach;
- capture escaping its allowed directory; and
- execution observations contradicting a claimed hard control.

These are assurance observations, not failures, for a contract that declared
them in advance:

- opaque internal model-call count;
- unavailable exact model revision;
- unobservable tool activity under `sandbox_contained` or `isolated_root`;
- missing usage charged at the full reservation; and
- a contained-transport token overrun, after charging it and pausing further
  dispatch.

## Provider Adapter Responsibilities

Provider-specific behavior stays in adapters, not in the neutral baseliner
prose or controller branching. Every provider adapter supplies deterministic
capability inspection, immutable request/invocation rendering, capture, usage
normalization, and normalized failure reasons. Each CLI adapter additionally
supplies:

- immutable command and effective-settings rendering;
- isolated root and environment construction;
- strongest available tool/sandbox restrictions;
- noninteractive input and one pinned capture strategy;
- streaming byte accounting and process-tree deadline enforcement;
- provider-event parsing for model, tool, and usage observations.

The shared executor owns dispatch IDs, durable captures, retries, ledger events,
certification, and artifact acceptance. The mandatory first-party parity scope
is Claude, Codex, Copilot, OpenCode, and OpenAI-compatible. The generic/plain
backend is admitted when its configured executable passes the same contained-CLI
minimum; an arbitrary executable is not assumed conformant merely because its
name appears in configuration. Adding a future first-party provider requires an
adapter conformance implementation, not changes to RE artifact semantics.

## Verification Strategy

Implementation proceeds test-first and must cover:

1. Protocol-2.0/2.1/2.2 manifests, catalogs, recovery, and continuation remain
   byte-for-byte compatible.
2. New v2 runs create protocol 2.3/schema 3 and pin executor-catalog schema 2.
3. Capability negotiation selects strict execution when every strict control is
   present and automatically selects the matching contained API or CLI class
   when any strict capability is missing, without changing provider.
4. Claude, Codex, Copilot, OpenCode, and OpenAI-compatible configurations all
   pass creation/shadow through their registered adapter; no API credential is
   required for a CLI-selected provider.
5. Every provider receives byte-identical context-bundle and authorial-schema
   authority for the same WorkItem.
6. Strict API execution retains one-call, no-tool, hard-token, exact-revision,
   deadline, capture, and recovery conformance.
7. Contained CLI launches once per dispatch, uses a fresh isolated root, does
   not place the live source or run authority in that root, and terminates the
   process tree at the hard deadline.
8. Native structured output and prompt-plus-strict-parser fallback normalize to
   the same candidate bytes; malformed prose is never heuristically repaired.
9. Disabled, snapshot-read-only, sandbox-contained, and isolated-root tool modes
   are reported exactly. A promised-denied tool escape produces executor
   failure; merely unobservable tool activity is never mislabeled as disabled or
   sandboxed.
10. Disabled/sandbox-contained fixtures cannot modify source or run-authority
    sentinels. Isolated-root fixtures receive no protected path or unsafe bypass,
    disclose the absence of technical isolation, and cannot turn any out-of-root
    output into authority. Candidate symlink, traversal, special-file, and
    extra-file attacks fail closed.
11. API and CLI execution inputs replay from their stored request/invocation
    envelopes after mutable configuration or provider defaults change. Stored
    CLI argv templates reject shell expansion, credential bytes, undeclared
    placeholders, and source/run-authority paths.
12. Trusted usage below reservation reconciles normally; unavailable usage
    charges the full reservation; observed overrun charges actual usage, emits
    durable overrun telemetry, and gates the next dispatch without discarding a
    valid artifact.
13. A remaining run budget below a contained dispatch-boundary reservation
    prevents request/process launch. Status distinguishes this pause from a hard
    per-request ceiling.
14. Requested-only model authority continues with the pinned alias and reports
    its limitation; exact-revision authority detects mismatch before acceptance.
15. Crash recovery never reissues a started dispatch, reconstructs assurance
    observations and charges from durable capture authority, and never invents
    unavailable usage or tool evidence.
16. Identical provider candidates from strict API, contained API, and contained
    CLI produce the same canonical artifact and certification while retaining
    distinct execution provenance.
17. Installed CLI smoke tests run a real clean multi-source workspace with Codex
    and at least one non-Codex CLI provider when credentials are available. The
    mandatory offline suite uses faithful executable fixtures for every adapter.
18. Status, shadow, and final banners show provider, execution assurance, token
    enforcement, tool control, model-revision assurance, artifact certification,
    quality scope, reservation/charge, and overruns without burying the terminal
    state.
19. The full RE v1 and protocol-2.2 isolation suites remain unchanged.

## Consequences

RE v2 becomes usable through the same provider selection as the rest of
Echelon. Semantic quality remains one contract, while resource/reproducibility
assurance is explicit and may vary by transport.

The design does not pretend that Echelon can hard-limit an opaque CLI agent
loop. Operators receive a conservative dispatch gate, hard wall-time and byte
bounds, durable actual-or-reserved charging, and prominent telemetry. A strict
API remains preferable for workloads where a hard token ceiling or exact model
revision is mandatory, but it is no longer required to obtain a valid RE v2
artifact.

Future selective deepening, audit, synthesis, reuse, and atomic repair must
consume this shared execution abstraction. They may request a minimum assurance
class for an explicitly assurance-sensitive operation, but they may not make
one provider's optional transport feature a hidden global prerequisite for RE.

## Completion Criteria

This correction is complete when:

- every first-party Echelon provider is admitted through strict or contained
  execution without silent provider replacement, and a generic backend is
  admitted whenever its executable passes contained-CLI conformance;
- the installed Codex real-workspace pilot passes baseline generation and
  certification rather than stopping at API-only preflight;
- at least one other CLI provider passes the same real or credentialed smoke
  path;
- protocol-2.2 runs remain byte-compatible and continuable;
- provider-neutral artifact equivalence and adapter-specific provenance are
  proven by the acceptance matrix;
- budget/status output distinguishes hard and dispatch-boundary enforcement;
  and
- the final RE banner states both semantic completion and execution assurance
  prominently.
