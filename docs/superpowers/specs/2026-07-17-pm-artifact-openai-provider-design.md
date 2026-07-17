# PM Artifact OpenAI Provider Design

**Status:** Approved design
**Date:** 2026-07-17
**Scope:** Phase A-style product artifact pipeline, Aha input ingestion, OpenAI-compatible artifact provider

## Problem

Echelon's current provider substrate is optimized for AI coding CLIs. The
existing Phase A and harness paths can route prompts through Claude, Codex,
Copilot, or opencode CLIs, and the build side relies on those tools having their
own file-editing and command-execution behavior.

The proposed product-manager pipeline has a different shape. It is artifact-only:
it should ingest product intent from Aha.io, run a controlled Phase A-style agent
process, and produce product artifacts, ledgers, and traceability evidence. It
must run in a data center as a service and call a local OpenAI-compatible LLM
endpoint, for example `http://127.0.0.1:8000/v1`. It should not depend on MCP,
LLM-side live Aha access, coding CLIs, repository mutation, build execution,
Docker worktrees, PR flow, or code verification.

The design needs a clean provider boundary so artifact-only providers cannot be
accidentally used for delivery/build commands, and future build-only providers
cannot be accidentally used for specification or product artifact commands.

## Goals

- Add a service-native design for a pure OpenAI-compatible artifact provider.
- Preserve Echelon's useful Phase A control ideas: explicit agent process,
  deterministic controller ownership, state, journal, ledgers, evidence, gates,
  validation, retries, and blocked states.
- Ingest Aha.io through a dedicated read-only CLI, not through MCP or live LLM
  tool access.
- Start each PM pipeline run from an explicit set of Aha idea and feature IDs.
- Treat the selected IDs as one related input set that produces one coherent
  product artifact package.
- Make the Aha CLI responsible for fetching, snapshotting, normalizing, hashing,
  and citing source inputs, not for deciding product meaning.
- Make the PM pipeline responsible for interpreting relationships, conflicts,
  assumptions, and downstream product artifacts.
- Require providers to declare artifact and build capabilities, and gate Echelon
  commands against those capabilities before execution.

## Non-Goals

- Do not implement build, delivery, code editing, sandbox execution, PR creation,
  or code verification for the PM pipeline.
- Do not let PM agents call Aha.io directly during reasoning.
- Do not introduce MCP as the Aha integration layer.
- Do not mutate Aha.io records in the first design.
- Do not recursively ingest entire Aha products, releases, or initiatives unless
  they are explicitly selected or are bounded context for selected records.
- Do not pretend an OpenAI-compatible chat-completions endpoint is an AI coding
  CLI with file tools.
- Do not merge the PM artifact pipeline into the current build harness as-is.

## Core Architecture

The PM pipeline is a separate artifact pipeline that reuses Echelon control
patterns without inheriting build machinery:

```text
Aha idea/feature IDs
  -> aha-ingest CLI
  -> immutable raw snapshots
  -> normalized product input model
  -> evidence ledger and source map
  -> PM artifact controller
  -> OpenAI-compatible artifact provider
  -> validated artifacts, ledgers, state, and journal
```

The controller is deterministic and owns all durable writes. LLM agents receive
bounded prompts and return structured text. The controller validates outputs,
writes files, appends journal entries, updates ledgers, advances phases, retries
invalid output, or blocks with a typed reason.

The model is a replaceable text worker. It does not own filesystem mutation,
source-of-record mutation, state transitions, or command execution.

## Aha Ingestion CLI

The Aha integration is a small dedicated CLI, provisionally named `aha-ingest`.
It accepts an explicit set of Aha idea and feature IDs:

```bash
aha-ingest --ids IDEA-123,FEATURE-456,FEATURE-789 --out runs/pm-001/input
```

Each selected idea or feature is a root input unit. The CLI may fetch tightly
bounded related records:

- For an idea: description, status, score/votes when useful, comments, custom
  fields, linked features, and lightweight product context.
- For a feature: description, status, release/product context, requirements,
  comments, custom fields, and linked ideas when available.
- For requirements: child records of selected features, not independent roots
  unless explicitly selected.
- For releases, initiatives, products, and workspaces: lightweight context only,
  not recursive ingestion.

The CLI writes both raw and normalized output:

```text
runs/<run-id>/input/
  raw/
    idea-123.json
    feature-456.json
    ...
  normalized/
    product-input.json
    product-input.md
    evidence-ledger.json
    source-map.json
```

Raw snapshots preserve the source response shape, IDs, URLs, timestamps, authors,
statuses, custom fields, comments, parent links, and child links available to the
CLI. Normalized records provide the stable contract consumed by the PM pipeline.

The CLI must be read-only. Authentication, rate limits, pagination, and API
errors are handled before the PM pipeline begins. A failed or partial snapshot is
a preflight outcome, not an agent reasoning problem.

## Related Input Set Model

The selected Aha IDs define one PM pipeline run and one related product artifact
package:

```bash
pm-pipeline run --aha-ids IDEA-123,FEATURE-456,FEATURE-789
```

The run declares its scope as:

```yaml
run_scope:
  mode: related_input_set
  root_source_ids:
    - AHA-IDEA-123
    - AHA-FEATURE-456
    - AHA-FEATURE-789
  relationship_policy: explicit_and_contextual
```

The Aha CLI does not decide product meaning. It normalizes and cites input. The
PM pipeline's first semantic phase produces an `input-relationship-map.md` that
states how the selected IDs relate, where they conflict, and whether any selected
record appears adjacent or follow-on rather than core scope.

Example relationship findings:

```text
- FEATURE-456 refines IDEA-123.
- FEATURE-789 is adjacent follow-on scope.
- REQ-12 and REQ-13 are child requirements of FEATURE-456.
- IDEA-123 and FEATURE-789 conflict on target persona.
```

The relationship map becomes explicit evidence for later artifacts. It is not
hidden chain-of-thought and is not treated as source truth; it is a pipeline
artifact that downstream phases may cite or challenge.

## Normalized Product Input Contract

The normalized input model preserves source identity aggressively:

```yaml
root_inputs:
  - source_id: AHA-FEATURE-456
    source_kind: feature
    source_url: https://...
    title: "..."
    description: "..."
    status: "..."
    parent_context:
      product: "..."
      release: "..."
      initiative: "..."
    child_requirements:
      - source_id: AHA-REQ-789
    linked_ideas:
      - source_id: AHA-IDEA-123
    evidence_refs:
      - aha://features/456#name
      - aha://features/456#description
      - aha://features/456#custom_fields.business_value
```

Every normalized unit has stable evidence references. Downstream product claims
must cite Aha evidence, prior pipeline artifacts, user input, or an explicit
assumption/open question. Uncited product claims are validation findings.

## PM Run Layout

Each run writes one coherent bundle:

```text
runs/<run-id>/
  input/
    raw/
    normalized/product-input.json
    normalized/product-input.md
    normalized/evidence-ledger.json
    normalized/source-map.json

  artifacts/
    input-relationship-map.md
    opportunity-brief.md
    product-brief.md
    requirements.md
    acceptance-criteria.md
    assumptions-ledger.md
    decision-ledger.md
    open-questions.md
    traceability-matrix.md

  state.json
  reasoning-journal.jsonl
```

`state.json` is the controller's resumable current state. The reasoning journal
is append-only and records dispatches, validation findings, phase decisions,
blocked reasons, and accepted structured results. Agents do not write either file
directly.

## Artifact Pipeline Phases

The initial PM pipeline should remain small and auditable:

1. Intake validation: confirm the normalized Aha package is complete and hash the
   source inputs.
2. Input relationship mapping: interpret how the selected IDs relate and surface
   conflicts, duplicates, adjacent scope, and missing context.
3. Problem framing: produce problem statement, personas/users, jobs, pains,
   desired outcomes, and success criteria.
4. Opportunity and product brief: synthesize a concise product direction and
   scope boundary.
5. Requirements and acceptance criteria: derive FR/NFR-style requirements,
   acceptance criteria, and non-goals.
6. Risk, assumption, and question pass: populate assumptions, risks, decisions,
   unresolved questions, and needed stakeholder follow-ups.
7. Consistency and traceability review: check contradictions, orphan
   requirements, weak evidence, unsupported claims, and unresolved blockers.
8. Final package: publish the artifact bundle and traceability matrix.

Each phase receives bounded context: normalized input, prior artifacts, active
ledgers, and the current phase contract. Each phase returns a structured result
block. The controller decides whether the result advances the run.

## OpenAI-Compatible Artifact Provider

The artifact provider calls a local or remote OpenAI-compatible API endpoint. The
first supported API surface is chat completions:

```text
POST <base_url>/chat/completions
```

Minimal configuration:

```yaml
providers:
  local-openai:
    kind: openai-compatible
    base_url: http://127.0.0.1:8000/v1
    model: local-model
    api_key_env: LOCAL_LLM_API_KEY
    timeout_ms: 600000
    temperature: 0.2
    max_tokens: 8192
    capabilities:
      - artifact
    features:
      streaming: false
      json_mode: false
      structured_outputs: false
      tool_calls: false
```

The provider should expose feature flags rather than assuming all compatible
servers support the same extensions. These flags are provider-local configuration
and do not imply global pipeline features.

The v1 artifact pipeline can operate with plain text output plus strict result
block validation. JSON mode or structured outputs may be enabled when the local
server supports them, but they are optimizations rather than required behavior.

The provider returns a normalized run result:

```text
exit_code
stdout
stderr
timed_out
token_usage
provider_error_code
raw_response_metadata
```

Timeouts, HTTP errors, malformed API responses, and invalid model output are
reported as provider results. The controller decides whether to retry, repair,
or block.

## Provider Capability Gate

Provider capability must be explicit. A provider may support artifact work,
build work, or both:

```text
artifact: can run specification, PM, and product artifact agents
build: can perform delivery, build, code execution, or implementation work
```

Implementation may use both a declared property and protocol/interface checks:

```python
class ProviderCapability(StrEnum):
    ARTIFACT = "artifact"
    BUILD = "build"

class EchelonProvider(Protocol):
    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        ...

class ArtifactProvider(Protocol):
    def run_artifact_agent(...):
        ...

class BuildProvider(Protocol):
    def exec_build(...):
        ...
```

Command dispatch validates capability before any provider call:

```text
echelon spec/run/change/bugfix
  requires provider capability: artifact

echelon delivery/build/harness
  requires provider capability: build
```

An artifact-only OpenAI-compatible provider must reject build/delivery commands:

```text
Provider "local-openai" supports artifact work only.
Command "echelon delivery ..." requires build capability.
Choose a build-capable provider.
```

A future build-only provider must reject specification/product artifact commands:

```text
Provider "future-build-provider" supports build work only.
Command "echelon spec ..." requires artifact capability.
Choose an artifact-capable provider.
```

The explicit `capabilities` property is the source of truth for user-facing
command gating and error messages. Method-level protocols provide implementation
safety but are not sufficient for clear command validation.

## Error Handling

The pipeline distinguishes deterministic preflight errors from model errors:

- Aha authentication, missing IDs, inaccessible records, pagination failures,
  and partial snapshots fail ingestion before agent dispatch.
- Unsupported normalized input schema versions block the PM pipeline before
  provider initialization.
- Provider transport failures may retry according to configured retry policy.
- Invalid structured model output triggers a repair prompt when safe, then blocks
  if repair fails.
- Unsupported or missing evidence citations produce validation findings and may
  route to repair or block depending on severity.
- Open questions and conflicts are allowed as artifacts, but publication requires
  they be explicitly listed and not silently converted into requirements.

No phase should silently degrade traceability. Degraded evidence is allowed only
when represented in the evidence ledger and final traceability matrix.

## Security and Operations

The Aha CLI is the only component with Aha credentials. It writes snapshots that
exclude secrets and token values. LLM prompts receive normalized product input
and evidence references, not API credentials.

The OpenAI-compatible provider can run fully inside the data center and target a
same-DC endpoint. Network policy should allow only the configured provider
endpoint for inference. Aha ingestion network access is separate and can run as a
controlled preflight step.

Run artifacts should be immutable after publication. Re-running the pipeline with
the same Aha snapshot should be possible without calling Aha again.

## Testing Strategy

Unit tests should cover:

- Provider capability parsing and command gating.
- OpenAI-compatible request construction, timeout handling, HTTP error handling,
  token usage extraction, and malformed response handling.
- Structured result extraction and validation from provider output.
- Aha normalized schema validation using fixture snapshots.
- Evidence reference generation and citation validation.
- Related input set handling, including linked ideas, feature requirements,
  adjacent scope, duplicates, and conflicts.

Contract tests should use a local stub OpenAI-compatible server that implements
`/v1/chat/completions` and returns deterministic model messages. Aha ingestion
tests should use recorded fixtures, not live Aha calls.

End-to-end tests should run a tiny artifact pipeline from fixture Aha snapshots
through final artifact publication and assert that all final product claims trace
to Aha evidence, prior artifacts, explicit assumptions, or open questions.

## Deferred Decisions

- Exact command names for the PM pipeline are deferred to implementation
  planning. The design uses `pm-pipeline` and `aha-ingest` as stable provisional
  names so architecture, provider boundaries, and artifact contracts are not
  blocked by CLI naming.
- The first write-back path to Aha is intentionally deferred. A later design can
  add a separate controlled publisher if product managers need generated
  artifacts returned to Aha.
- The exact normalized schema can evolve during implementation, but it must
  preserve source IDs, source URLs, source fields, timestamps, hashes, and stable
  evidence references from the first version.
