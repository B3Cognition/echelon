# RE v2 Prosaic-First Provider Execution Design

**Date:** 2026-08-23
**Status:** Revised after rejection of RE-owned provider execution; written-spec
review pending
**Relationship:** Corrects the API-only execution path introduced by
`2026-08-21-re-v2-layered-baseline-design.md`

## Purpose

RE v2 must follow the same model-execution architecture as Echelon spec and
delivery. Prosaic owns neutral agent prose and neutral execution metadata.
Echelon loads that authority through Prosaic and dispatches it through the
workspace's normally configured AI coding provider. Provider adapters translate
the neutral metadata to provider-specific models and controls.

The non-negotiable invariant is:

> Every RE model invocation is a pinned Prosaic agent invocation dispatched
> through Echelon's shared AI coding provider path.

No RE module may choose a concrete model, open a provider HTTP connection,
launch a provider binary, read provider credentials, or independently interpret
Prosaic execution metadata.

This invariant applies only to model-backed work. Deterministic work must not
acquire a fake Prosaic or provider dependency merely for architectural
uniformity.

## Current L0/L1 Verification

The current implementation has different answers for the two implemented
layers:

- **L0 is correct:** inventory, partitioning, and evidence-pack construction use
  `DeterministicExecutionDependenciesV1` and the in-process deterministic
  executor. L0 makes no model call, so it neither uses nor should use Prosaic.
- **L1 is incorrect:** it is model-backed but does not execute a normally
  inspected Prosaic agent through the shared provider path.

The verified L1 divergences are:

- `_re_v22_agent_bytes` reads the installed Markdown file as raw bytes instead
  of inspecting it through Prosaic, so YAML frontmatter becomes prompt text.
- The protocol hashes those raw bytes but does not pin the separately parsed
  agent body and frontmatter authority.
- `BoundedApiBaselineExecutor` opens an HTTP connection itself, reads
  `OPENAI_API_KEY`, selects a concrete model, and accepts only the
  `openai-compatible` provider.
- The executor takes RE-owned reasoning settings instead of the Prosaic
  agent's `model_tier` and `effort` metadata.
- The baseliner currently declares `tools: write`, while its prose says never to
  invoke a tool. The metadata and invariant protocol therefore contradict each
  other.

These are architectural defects, not merely missing Codex support. Adding more
RE-specific transports would duplicate the provider layer and preserve the
wrong ownership boundary.

## Decision

Protocol 2.3 has exactly two execution kinds:

1. `deterministic_in_process` for controller-owned computation with no model
   invocation; and
2. `prosaic_agent` for every model-backed producer.

`prosaic_agent` means all of the following:

- the agent is defined under `prosaic/subagents/`;
- the installed workspace authority is inspected through
  `ProsaicPromptLoader`;
- the separated body and frontmatter are pinned in the run;
- the body is dispatched through `SquadCliProvider`, which delegates to
  `AICodingCliProvider` and the selected shared provider adapter;
- the frontmatter is supplied as `prompt_metadata` rather than copied into the
  prompt body; and
- the normal shared result-contract validator remains authoritative.

RE has no API, CLI, strict, contained, or fallback execution modes of its own.
Transport is an implementation detail of the shared provider adapter. RE may
record which controls the selected adapter could enforce, but those observations
must not create a parallel provider-selection system.

## Options Considered

### Prosaic plus the shared provider path — selected

This is the architecture already established for spec and delivery. It keeps
agent intent provider-neutral and puts provider-specific translation in one
place.

### RE-specific capability-negotiated transports — rejected

The earlier protocol 2.3 proposal added `strict_bounded`, `contained_api`, and
`contained_cli` executors. This would make RE a second provider framework,
cause feature drift, and let RE configuration override Prosaic authority.

### Force Prosaic into deterministic L0 — rejected

L0 inventory and evidence construction contain no model work. Requiring Prosaic
there would add a failure mode without adding semantic authority. The correct
verification is that L0 runs without Prosaic or a provider, while every L1 call
provably passes through both.

## Layer Boundary

### L0: deterministic inventory

L0 remains controller-owned and deterministic:

- execution kind is `deterministic_in_process`;
- agent authority and agent hashes are null;
- provider and model attempts are zero;
- provider input and output tokens are zero;
- no provider object is created; and
- no Prosaic executable, installed agent bundle, provider CLI, provider
  credential, or network connection is required.

An inventory-only run must complete when all Prosaic and provider facilities are
unavailable. If future L0 work requires a model, that work is either reclassified
above L0 or implemented as a Prosaic agent invocation.

### L1: compact baseline

L1 is model-backed and therefore has execution kind `prosaic_agent`. Its work
item names:

- the neutral agent ID `echelon.re-baseliner`;
- the pinned Prosaic authority artifact;
- its deterministic L0 and context-pack dependencies;
- the result contract and candidate path; and
- controller-owned budget reservations.

The controller dispatches the pinned body through `SquadCliProvider` and passes
the pinned frontmatter as `prompt_metadata`. The provider produces an isolated
candidate and a structured `echelon_result`. The existing deterministic capture,
schema validation, evidence checks, certification, and publication rules remain
authoritative.

The graph validator enforces an exclusive choice: deterministic nodes have no
agent authority, and model-backed nodes have one pinned Prosaic authority.

## End-to-End Authority Flow

```text
prosaic/subagents/echelon.re-baseliner.md
                      |
             workspace installation
                      |
      ProsaicPromptLoader / `prosaic inspect`
                 /                    \
        neutral body            neutral frontmatter
                 \                    /
              pinned run authority
                      |
               SquadCliProvider
                      |
             AICodingCliProvider
                      |
     configured shared provider adapter
       (Claude / Codex / Copilot / OpenCode /
              OpenAI-compatible / generic)
                      |
       isolated baseline + echelon_result
                      |
     controller capture, validation, certification
```

This is the only model-execution flow allowed in RE v2.

## Prosaic Inspection Authority

At run creation, before publishing a manifest for model-backed work, the
controller calls:

```python
ProsaicPromptLoader(workspace_root).load_subagent("echelon.re-baseliner")
```

The loader invokes Prosaic inspection against the installed
`.echelon/prosaic` source. A missing executable, missing installed agent,
inspection failure, or malformed frontmatter fails creation before the manifest
becomes authoritative. The diagnostic tells the operator when workspace
migration or installation is required.

The controller stores a `ProsaicAgentAuthorityV1` artifact containing:

```yaml
schema_version: 1
artifact_id: <content-addressed ID>
artifact_type: prosaic_agent_authority
agent_id: echelon.re-baseliner
body_hash: sha256:<hash>
frontmatter_hash: sha256:<hash>
frontmatter:
  name: echelon.re-baseliner
  description: <neutral description>
  execution: agent
  tools: write
  color: orange
  model_tier: strong
  effort: high
inspection:
  loader_schema_version: 1
  receipt_hash: sha256:<hash>
```

The exact inspected body is stored as a run artifact. Continuation and retry use
the pinned body and frontmatter; they do not silently re-read a changed installed
agent. A new agent revision requires a new run authority rather than mutating an
existing run.

An L0-only run does not inspect or pin an unused agent.

## Frontmatter Authority

Prosaic frontmatter is the sole authority for model intent:

- `model_tier` expresses the neutral model capability tier;
- `effort` expresses the neutral reasoning-effort request;
- `tools` expresses the neutral tool capability;
- `execution` expresses the execution form; and
- `name` identifies the agent.

RE configuration must not add a compact-baseline concrete model, model revision,
reasoning effort, or provider-specific tool policy. Workspace configuration
selects the provider and the ordinary shared provider mappings, exactly as it
does for other Echelon features.

The run records the selected provider and observed effective model/effort for
diagnostics and reproducibility. Those observations do not replace the pinned
neutral authority and do not become cross-provider eligibility gates.

## Shared Provider Mapping

Shared provider adapters—not RE—translate the baseliner's neutral metadata:

- `model_tier: strong` to the provider's configured strong model;
- `effort: high` to the closest supported reasoning control;
- `tools: write` to the closest safe provider-native capability; and
- `execution: agent` to the normal agent execution path.

Current adapters already map model tiers unevenly, while effort and tools are
not uniformly enforced. That is a shared provider-layer defect. The
implementation must close it in the common adapter contracts and tests so spec,
delivery, and RE receive the same behavior.

When a provider cannot express an exact control, its adapter applies the same
documented fallback used by other Echelon workflows and records the effective
control. Lack of an exact revision, hard output-token ceiling, native no-tools
switch, or reasoning-effort flag does not make that provider ineligible and
must not cause RE to substitute another provider.

## Agent Tool and Output Contract

`tools: write` is intentional. The baseliner receives a fresh isolated execution
root containing only:

- the immutable context pack;
- the candidate schema and instructions; and
- an empty designated output path, `baseline.json`.

The live source tree, run-control files, registry, manifest, and accepted
artifacts are not exposed as writable agent authority. The agent protocol is
revised to say:

- ALWAYS consume only the supplied immutable context;
- ALWAYS write exactly the designated candidate file;
- ALWAYS return the normal structured `echelon_result` declaring
  `candidate_ready` and the candidate path;
- NEVER discover or read the live source workspace;
- NEVER write controller-owned state or accepted artifacts; and
- NEVER claim semantic-audit or workspace-synthesis completion.

Candidate capture rejects missing files, extra files, symlinks, path escape,
schema violations, and evidence references outside the immutable pack.

The shared `SquadCliProvider` result validator is the only result-contract
authority. RE must not infer or synthesize success from prose or merely from a
file appearing. Internal automatic result repair is disabled for this dispatch;
a malformed result becomes a durable counted RE attempt followed by the normal
RE retry policy.

## Provider Selection and Switching

Each new dispatch resolves the provider through the ordinary Echelon
configuration cascade. RE contains no hidden provider override, API-key lookup,
or fallback provider.

The run pins the Prosaic authority, snapshot, policy, context, and certifier. It
does not pin a concrete provider as semantic authority. A continuation may use a
newly configured provider for unresolved work, matching existing Echelon
behavior. Every dispatch receipt records the configured provider adapter,
reported model, effective controls, and usage so a provider switch is visible.

Already accepted artifacts remain immutable and are not regenerated solely
because the configured provider changes.

## Budget Semantics

The existing run-wide token and wall-time budgets remain controller authority.
Before a model dispatch, the controller durably reserves its maximum allowed
spend. Controller operational metadata—dispatch ID, result schema, isolated
paths, and reservations—is separate from Prosaic frontmatter and cannot
overwrite `model_tier`, `effort`, `tools`, `execution`, or agent identity.

Shared adapters return normalized usage and enforcement telemetry:

- actual trusted usage is charged when available;
- unknown or untrusted usage charges the full reservation;
- wall time and controller-observed bytes remain hard local limits; and
- provider-side hard caps versus dispatch-boundary limits are reported honestly.

Budget policy controls whether a dispatch may start and how usage is charged. It
does not select a weaker model or change Prosaic effort.

## Durable Dispatch and Recovery

Before invoking a provider, the controller commits a `ProsaicDispatchInputV1`
containing:

```yaml
schema_version: 1
dispatch_id: <stable unique ID>
work_item_id: <ID>
attempt_number: <integer>
agent_authority_id: <artifact ID>
agent_body_hash: sha256:<hash>
frontmatter_hash: sha256:<hash>
context_pack_id: <artifact ID>
context_pack_hash: sha256:<hash>
result_contract: <shared contract ID>
candidate_path: baseline.json
controller_scope:
  source_id: <source ID>
  domain_id: <domain ID>
reservation:
  token_limit: <integer>
  wall_time_seconds: <integer>
```

The selected provider and effective provider observations belong in the dispatch
receipt because they are resolved at execution time. They do not belong in the
semantic work item or artifact identity.

Recovery follows the existing durable-dispatch rules:

1. commit `dispatch_started` before external execution;
2. never issue the same `dispatch_id` twice;
3. adopt a complete isolated capture when its hashes and result contract verify;
4. otherwise mark the attempt abandoned, charge it conservatively, and create a
   new attempt with a new dispatch ID; and
5. publish only after deterministic certification succeeds.

## Protocol Compatibility

Protocol 2.3 uses manifest schema 3 and adds an optional catalog of pinned
Prosaic agent authorities. It preserves protocol 2.2 artifact identity, policy,
producer, L0, capture, certification, and publication rules where they do not
conflict with this design.

Protocols 2.0 through 2.2 remain readable for validation, status, and recovery.
New 2.2 runs are disabled after 2.3 ships.

Because every new model invocation must use Prosaic, an unresolved 2.2 run may
adopt and certify an already completed direct-executor capture, but it may not
issue another direct provider request. Status explains that unresolved L1 work
requires a new 2.3 run. Deterministic L0 artifacts can be reconstructed or
reused according to their existing content-addressed rules; L1 adoption remains
a distinct explicitly validated operation.

The old direct HTTP executor remains only as historical protocol-reading code
until its compatibility window ends. It is not registered for new dispatch.

## Status and Telemetry

Status makes the layer boundary explicit.

For L0 it reports:

- execution: deterministic in process;
- Prosaic agent: not applicable;
- provider/model attempts: 0;
- provider tokens: 0; and
- quality scope: inventory and evidence only.

For L1 it reports:

- agent: `echelon.re-baseliner` and pinned authority hash;
- neutral model intent: `strong`;
- neutral effort: `high`;
- neutral tools: `write`;
- configured provider and reported effective model/controls;
- usage and token-limit enforcement class;
- compact-baseline certification result; and
- quality scope: L1 compact baseline, not semantic audit or workspace synthesis.

Provider limitations are telemetry, not a reason to bypass Prosaic or silently
change provider.

## Future Layers

The graph schema generalizes this rule to L2 and later work:

- every deterministic node declares `deterministic_in_process` and has no agent;
- every model-backed node declares `prosaic_agent` and names one pinned Prosaic
  authority; and
- graph validation rejects a node that declares both or neither execution
  authority.

Adding L2 repair, semantic audit, synthesis, or other model-backed work therefore
requires adding or selecting a neutral Prosaic agent, not adding a provider call
inside RE.

## Failure Semantics

Run creation fails before manifest publication when:

- required Prosaic inspection is unavailable or invalid;
- the required agent is missing from the installed workspace bundle;
- required neutral metadata is missing or malformed; or
- the configured shared provider is unavailable under normal Echelon rules.

A started provider attempt fails durably and counts against retry/budget policy
when:

- provider execution fails;
- the shared result contract is absent or malformed;
- candidate capture fails; or
- deterministic certification rejects the candidate.

Path escape, unexpected mutation, authority mismatch, and receipt/hash mismatch
remain safety failures.

Missing exact model revision, exact internal request count, trusted token usage,
or provider-native hard caps are reported as limitations. They do not authorize
a bypass around Prosaic and do not justify a provider substitution.

## Verification Matrix

### L0 boundary

1. An inventory-only run completes with Prosaic execution mocked unavailable,
   the installed Prosaic bundle absent, provider construction set to fail,
   credentials absent, and network/provider binaries unavailable.
2. Every L0 producer has `deterministic_in_process`, null agent authority, zero
   provider attempts, and zero provider tokens.
3. Provider and Prosaic spies observe zero calls during L0 execution.
4. Protocol 2.3 produces the same deterministic L0 bytes as protocol 2.2 for the
   same snapshot and policy.

### L1 Prosaic authority

5. Run creation calls `ProsaicPromptLoader.load_subagent` for the baseliner and
   fails atomically on missing or malformed authority.
6. The exact inspected body and canonical frontmatter are separately hashed,
   stored, and reused on continuation.
7. A provider spy receives the exact body without YAML frontmatter and receives
   `name`, `execution: agent`, `model_tier: strong`, `effort: high`, and
   `tools: write` through `prompt_metadata`.
8. Static architecture tests reject provider SDK/network imports, provider
   binary launches, credential lookup, concrete model mappings, and direct
   backend construction under the protocol 2.3 RE package.
9. Every L1 dispatch passes through `SquadCliProvider` and the shared result
   validator; tests prove RE cannot synthesize a successful result.
10. Retry reuses the pinned Prosaic authority, creates a new dispatch ID, and
    records any configured provider change in the receipt.

### Shared provider behavior

11. Contract tests cover neutral `strong`, `high`, `write`, and `agent`
    translation or documented fallback for every first-party provider adapter.
12. No RE configuration field can select a concrete model or override protected
    Prosaic metadata.
13. Codex, Claude, Copilot, OpenCode, OpenAI-compatible, and generic configured
    providers remain eligible through the shared path.
14. A real Codex-provider pilot proves inspected Prosaic authority, isolated
    candidate output, shared result validation, certification, and telemetry.
15. At least one non-Codex provider fixture or authenticated pilot proves the
    same provider-neutral flow.

### Recovery and compatibility

16. Crash-before-dispatch, crash-after-provider, crash-after-capture, and
    crash-after-certification tests preserve at-most-once dispatch IDs and
    conservative charging.
17. A changed installed Prosaic agent does not mutate an existing run's pinned
    authority.
18. Provider switching affects only unresolved dispatch receipts and does not
    stale accepted artifacts.
19. Protocol 2.0 through 2.2 runs remain readable.
20. An unresolved 2.2 run cannot issue a new direct provider request after 2.3
    activation and receives an actionable migration diagnostic.
21. Status distinguishes L0 deterministic completeness from L1 Prosaic-backed
    compact-baseline completeness and from later full-quality layers.

## Consequences

This design removes the false choice between provider parity and semantic
quality. RE receives the same provider portability as spec and delivery because
it uses the same architecture. Provider limitations remain visible without
becoming RE-specific eligibility policy.

The main implementation cost is that shared provider metadata handling must be
made consistent, particularly for effort and tools. That work benefits all
Echelon workflows and belongs in the shared layer.

## Completion Criteria

The correction is complete when:

- L0 is proven fully deterministic and independent of Prosaic/provider runtime;
- every L1 model call uses a pinned inspected Prosaic agent;
- every such call passes through the shared provider facade and result contract;
- no active RE v2 path owns provider transport, credentials, concrete models,
  or metadata translation;
- the baseliner's `tools: write` contract and prose agree;
- shared adapters honor or truthfully degrade neutral model, effort, and tool
  metadata across all supported providers;
- recovery and budgets remain durable and provider-neutral; and
- operator status states both the execution authority and the achieved quality
  layer without implying full RE completion.
