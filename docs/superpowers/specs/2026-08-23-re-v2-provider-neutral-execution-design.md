# RE v2 Prosaic Shared-Provider Integration Design

**Date:** 2026-08-23
**Status:** Revised after full reuse audit; written-spec review pending
**Relationship:** Replaces protocol 2.2's API-only L1 executor without replacing
the protocol 2.2 execution kernel or Echelon's provider architecture

## Purpose

Every model-backed RE operation must use the same execution path as Echelon spec
and delivery:

```text
ProsaicPromptLoader
  -> ProsaicCommandArtifact(body, frontmatter)
  -> SquadCliProvider.exec_agent(prompt_metadata=frontmatter)
  -> AICodingCliProvider
  -> configured provider adapter
```

RE must not select concrete models, interpret neutral metadata, open provider
connections, launch provider binaries, read credentials, or add a second
provider abstraction.

The implementation is a thin integration into the existing protocol 2.2
kernel. It is not a new execution framework.

## Current State

- L0 inventory, partitioning, evidence, and context construction are already
  deterministic in-process operations. They make no model call and must not
  load Prosaic or construct a provider.
- L1 currently reads the baseliner Markdown as raw bytes and uses the direct
  `BoundedApiBaselineExecutor`. That bypasses Prosaic inspection and restricts
  L1 to the OpenAI-compatible API.
- Echelon already loads Prosaic body/frontmatter correctly for other workflows,
  forwards frontmatter through `SquadCliProvider`, maps it in provider adapters,
  validates `echelon_result`, and records normalized invocation telemetry.
- Protocol 2.2 already implements the graph, executor catalog, content-addressed
  object store, execution input, candidate capture, certification, budget,
  ledger, recovery, materialization, status, and final-state banner.
- `ExecutorContractEntryV1` already recognizes `execution_mode: cli`; only the
  provider preparation/capture/controller branches remain API-specific.

## Reuse Matrix

| Need | Existing authority to reuse | Permitted change |
|---|---|---|
| Load agent body and metadata | `ProsaicPromptLoader.load_subagent` and `ProsaicCommandArtifact` | Serialize the existing artifact canonically for the existing agent-contract hash |
| Provider selection and metadata mapping | `SquadCliProvider`, `AICodingCliProvider`, and existing adapters | None; pass pinned frontmatter unchanged |
| Result validation | `EchelonResultContract` and `SquadCliProvider.exec_agent` | Define one RE dispatch contract using existing fields |
| Agent authority | `RequestRendererAuthorityV1.agent_contract_hash`, `InstalledAuthorityRegistry.agent_contracts`, and `ObjectStore` | Store canonical inspected artifact bytes instead of raw Markdown for new 2.3 runs |
| Execution identity | `ExecutionInputV1` and `PreparedExecutionV1` | Generalize the existing provider branch to permit CLI without an API envelope |
| Executor selection | `ExecutorContractEntryV1` and `ExecutorContractCatalogV1` | Add one shared-AI-CLI adapter entry using the already-declared `cli` mode |
| Candidate isolation and capture | Existing candidate root, `Protocol22ExecutionStore`, candidate inventory, capture, and commit | Generalize `execution_mode` from API-only to provider-backed API or CLI |
| Usage and budget | `DispatchReservationV1`, `NormalizedUsageV1`, protocol-2.2 budget replay | Canonically persist the existing normalized usage value; retain full-reservation charging when usage is unavailable or untrusted |
| Retry and recovery | Protocol-2.2 events, controller, recovery, and at-most-once dispatch IDs | Generalize API checks to provider-backed checks; add no new recovery machine |
| Certification and artifacts | Existing baseline parser, certifier, receipts, ledger, and materialization | None |
| Status and banner | Existing protocol-2.2 status renderer | Report configured provider/model telemetry already returned by the shared provider |
| Protocol compatibility | `RunManifestV2`, schema 2, existing catalog/input files | Accept protocol `2.3` in the same schema; do not create schema 3 |

## Explicitly Rejected Duplicates

The implementation must not add:

- a `ProsaicAgentAuthorityV1` wrapper around `ProsaicCommandArtifact`;
- a goal-aware Prosaic loader parallel to ordinary creation/graph branching;
- a new Prosaic authority catalog parallel to `agent_contracts`;
- a `ProsaicDispatchInputV1` parallel to `ExecutionInputV1`;
- a protocol-2.3 object store, candidate store, event schema, budget, ledger,
  recovery controller, materializer, or status implementation;
- shared-provider metadata normalization already owned by provider adapters;
- an RE-owned API/CLI/provider factory; or
- manifest schema 3 when schema 2 already holds the required catalog and input
  references.

## Protocol Decision

New baseline runs identify themselves as engine protocol `2.3` while retaining
run-manifest schema `2`. Protocol 2.3 means:

- deterministic producer entries remain exactly the protocol-2.2 entries;
- compact-baseline producer entries use `execution_mode: cli` and the shared
  AI coding provider adapter;
- the agent contract object contains canonical inspected
  `ProsaicCommandArtifact` body/frontmatter rather than raw Markdown; and
- all other graph, identity, storage, certification, budget, recovery, and
  status behavior remains the existing schema-2 behavior.

Protocols 2.0 through 2.2 remain readable. New 2.2 baseline creation is disabled
when 2.3 ships. An old 2.2 run may validate or adopt an already committed
capture, but it may not issue a new direct provider request.

The schema-1 `re_v2.controller.ProviderProcessWorkExecutor` is not a missing
shared-provider adapter for this work. It owns the legacy process/lease/event
contract for protocols 2.0 and 2.1, while schema 2 already has a different
execution-input, capture-commit, budget, and recovery chain. Routing 2.3 through
that controller would replace or duplicate the protocol-2.2 kernel. Protocol
2.3 therefore extends schema 2's already-declared `cli` executor seam and reuses
only the common `SquadCliProvider` below both orchestration layers.

## L0 Boundary

Inventory/L0 creation selects only deterministic executor entries. Therefore it:

- does not call `ProsaicPromptLoader`;
- does not construct `SquadCliProvider` or any provider adapter;
- records zero provider attempts and tokens; and
- remains byte-identical to protocol 2.2 for the same snapshot and policy.

This boundary is enforced by tests that make Prosaic loading and provider
construction raise if touched during an inventory run.

## L1 Agent Authority

For a baseline run, creation calls the existing:

```python
artifact = ProsaicPromptLoader(project_root).load_subagent(
    "echelon.re-baseliner"
)
```

Missing authority fails before manifest publication with workspace migration
guidance. The returned `ProsaicCommandArtifact` is serialized canonically as:

```json
{"body":"<inspected body>","frontmatter":{"name":"echelon.re-baseliner"}}
```

The example is abbreviated; the stored frontmatter is the complete inspected
mapping. The existing `ObjectStore` stores these bytes, the existing
`agent_contract_hash` identifies them, and the installed-authority registry maps
the agent ID to that hash. Continuation reads the run-pinned object; it does not
reinspect mutable installed prose.

No additional authority model is required.

## Shared Provider Dispatch

The only genuinely new runtime component is a thin compact-baseline executor
adapter around `SquadCliProvider`. It:

1. verifies the existing executor, execution input, agent-contract hash,
   context hash, response-schema hash, reservation, candidate root, and deadline;
2. decodes the run-pinned `ProsaicCommandArtifact`;
3. renders the existing compact-baseline context/schema instructions;
4. calls `SquadCliProvider.exec_agent` in the existing isolated candidate root;
5. supplies the pinned frontmatter as `prompt_metadata` without interpreting or
   replacing `model_tier`, `effort`, `tools`, or `execution`;
6. disables automatic result repair so retries remain visible to the RE budget;
7. uses strict shared `EchelonResultContract` validation; and
8. adapts `SquadAgentResult` into the existing `RawExecutionResultV1` capture
   surface, including the provider/model observations already returned by the
   shared provider.

The adapter never constructs a concrete backend. `SquadCliProvider` performs
the existing configuration cascade and provider dispatch.

## Candidate and Result Contract

The baseliner's intentional `tools: write` authority is restricted by the
existing isolated candidate root. It writes exactly `baseline.json` and returns:

```yaml
echelon_result:
  verdict: DONE
  state_updates: {}
```

The adapter supplies:

```python
EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)
```

The existing candidate scanner rejects missing/extra files, symlinks, special
files, path escape, and invalid bytes. The existing certifier validates schema,
evidence, utility, and scope. A valid result without a valid candidate is not
success; a valid candidate with malformed result follows the existing
result-contract reconstruction/retry rules.

## Frontmatter and Provider Behavior

The adapter passes the complete pinned frontmatter unchanged. Existing provider
handling remains authoritative:

- provider selection follows normal workspace configuration;
- model-tier, effort, and tool behavior follow the selected adapter's existing
  mapping/fallback behavior;
- provider-specific limitations remain normal provider telemetry; and
- RE does not make an adapter eligible or ineligible based on optional controls.

If a provider adapter has a general metadata deficiency, that is a separate
provider-layer issue affecting all workflows. It is not part of RE 2.3 unless a
real RE integration test exposes a regression in an already-supported behavior.

## Budget and Usage

Protocol 2.3 reuses the protocol-2.2 reservation and replay structures. CLI
dispatch uses a conservative reservation derived from the existing executor
limits and context/prompt bounds. `SquadAgentResult.token_usage` and
`token_usage_details` are converted to the existing `NormalizedUsageV1` value
and stored canonically through the existing provider-usage blob slot:

- complete trustworthy usage is charged as observed;
- missing or incomplete usage is marked unavailable/untrusted and charges the
  full reservation through existing budget replay;
- observed usage above reservation remains an existing breach signal; and
- wall time remains the existing hard local deadline.

No new budget schema or accounting engine is introduced.

The existing `ExecutionCaptureV1.provider_name` and
`resolved_model_revision` slots persist the shared provider's observed provider
and model values. The legacy field name does not turn an observed CLI model
name into immutable model-revision authority; Prosaic frontmatter plus the
selected provider adapter remain the request authority.

## Durable Execution and Recovery

The existing ordering remains unchanged:

```text
prepare existing ExecutionInputV1
  -> durable dispatch_started
  -> shared provider invocation
  -> existing capture and commit
  -> dispatch_observed
  -> existing candidate persistence/certification/acceptance
```

For CLI mode, `ExecutionInputV1` uses its existing agent-contract and context
hashes. Its API-envelope hash is null because there is no API request envelope;
the pinned agent, context, response schema, executor implementation digest, and
fixed renderer contract deterministically define the prompt.

Certification loads the already-pinned context bytes through
`ExecutionInputV1.context_bundle_hash`. It does not depend on an API message
envelope and does not introduce a second context container.

Recovery continues to use existing dispatch IDs and capture states. A started
dispatch is never reissued. An incomplete abandoned dispatch is charged at its
reservation and may create a new retry dispatch only under existing retry
limits.

No parallel recovery state machine is allowed.

## Minimal Code Surface

Expected implementation changes are limited to:

- `prosaic/subagents/echelon.re-baseliner.md`: align write/result prose with the
  shared result contract;
- `src/harness/re_v2/protocol_22/executors.py`: resolve the already-supported
  CLI execution mode without concrete model authority;
- `src/harness/re_v2/protocol_22/execution.py`: generalize existing provider
  preparation/capture from API-only to API-or-CLI;
- `src/harness/re_v2/protocol_22/model.py`: allow protocol 2.3 in schema 2 and
  CLI capture/input nullability without adding fields;
- `src/harness/re_v2/protocol_22/provider.py`: retain shared rendering/usage
  value helpers, add canonical encoding for the existing normalized usage
  value, and carry observed provider/model values on the existing raw-result
  surface; no new transport;
- one focused thin adapter file, `src/harness/re_v2/protocol_22/cli_provider.py`;
- `src/harness/re_v2/protocol_22/controller.py` and `recovery.py`: generalize
  existing provider-backed branches;
- `src/harness/re_v2/run_store.py` and `src/echelon/cli.py`: select/read protocol
  2.3 and use existing Prosaic/provider factories; and
- existing status/tests where protocol literals or provider labels are closed.

No other new production package is expected.

## Verification

1. L0 completes with Prosaic loading and provider construction set to fail.
2. L1 creation calls the existing Prosaic loader exactly once and stores the
   exact inspected body/frontmatter through the existing object store.
3. A `SquadCliProvider` spy receives the exact body-derived prompt and complete
   pinned frontmatter; no YAML frontmatter appears in prompt text.
4. Static tests show no provider backend construction, credential lookup,
   concrete model mapping, or network code in RE's CLI adapter.
5. Existing Claude/Codex/OpenAI-compatible metadata-mapping tests remain
   unchanged and pass; RE adds no duplicate mapping tests.
6. The standard shared result validator accepts `DONE` with empty updates and
   rejects missing/malformed/extra control output without internal repair.
7. Existing candidate, certification, budget, ledger, recovery, and status
   suites pass for both API 2.2 fixtures and CLI 2.3 fixtures; CLI certification
   reads the context named by the execution input rather than an API envelope.
8. Schema-1 and protocol-2.2 canonical compatibility tests remain unchanged.
9. A real Codex workspace pilot completes L1 through the shared provider path.
10. One non-Codex provider fixture proves the same adapter boundary without
    adding provider-specific RE code.

## Completion Criteria

The correction is complete when:

- redundant protocol-2.3 authority/provider/budget/recovery abstractions are
  absent;
- L0 has zero Prosaic/provider interaction;
- every L1 model call loads Prosaic and uses `SquadCliProvider`;
- existing provider metadata handling is reused unchanged;
- protocol-2.2 graph, identity, storage, candidate, certification, budget,
  ledger, recovery, and status machinery carry protocol 2.3;
- old protocols remain readable without new direct provider calls; and
- real-provider telemetry shows the configured provider performed the work.
