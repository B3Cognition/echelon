# Echelon Stacks Design

**Status:** Proposed
**Date:** 2026-07-05
**Deciders:** Echelon maintainers

## Context

Echelon needs an opt-in way to steer generated applications toward known
Stats Perform technology bundles without scattering conditional prompt prose
across agents.

The first target stacks are:

- `statsperform-playbook`: Playbook UI, component, design-token, form, testing,
  and compliance guidance for web apps.
- `statsperform-msa-service`: CAIC MSA service template and MSA core
  conventions for Python/FastAPI services.
- `statsperform-stark-webapp`: Opta Stark web application archetype for
  Nx/Next.js web apps, including its web-app delivery conventions.

The stack model must also handle infrastructure capabilities such as databases,
messaging, and stream processing. These should be independent capability stacks
so a service can opt into MSA plus Kafka, MSA plus Postgres, or a Flink data
pipeline without making those choices implicit in the service archetype.

The default must remain current Echelon behavior: infer the stack from
requirements and repository evidence unless the user explicitly opts in.

Speckit presets are useful prior art, but Echelon should not extend speckit
presets directly. Echelon may move away from speckit, and these stacks need
machine-readable capability semantics rather than template replacement alone.

## Goals

- Add an Echelon-native stack model independent of speckit presets.
- Keep stack selection opt-in; absence of selected stacks means normal Echelon
  inference.
- Model stacks as composable, schema-backed capability bundles.
- Resolve stack implications, conflicts, requirements, and context before agent
  dispatch.
- Generate deterministic machine context and concise agent-readable context.
- Let future stacks be added without editing core agents.
- Support products with multiple target archetypes, for example a web app plus
  an MSA backend service.
- Support non-application capability stacks such as databases, messaging, and
  stream-processing engines.

## Non-Goals

- Do not make Playbook, MSA, or Stark global defaults.
- Do not make Stark a generic deployment stack for services.
- Do not make MSA imply a database, Kafka, Flink, or any other infrastructure
  dependency unless a dedicated stack explicitly declares it.
- Do not extend or depend on speckit preset behavior.
- Do not encode stack-specific `if stack then ...` branches inside agent prose.
- Do not make the initial implementation install or update external repos.

## Decision

Introduce **Echelon Stacks**.

An Echelon stack is a composable, schema-backed bundle of capabilities,
constraints, tools, requirements, and agent context.

Stacks are selected in committed Echelon config:

```yaml
stacks:
  target_archetypes:
    - web_app
    - service
  selected:
    - statsperform-playbook
    - statsperform-msa-service
```

If `stacks.selected` is absent or empty, Echelon keeps its existing inference
path.

Bundled stacks live under:

```text
extension/stacks/
  statsperform-playbook/
    stack.yml
    context.md
  statsperform-msa-service/
    stack.yml
    context.md
  statsperform-stark-webapp/
    stack.yml
    context.md
```

Resolved stack output lives under runtime context:

```text
.echelon/context/stacks/resolved.yml
.echelon/context/stacks/resolved.md
```

The YAML output is for deterministic orchestration and validation. The Markdown
output is the only stack context agents read.

## Stack Schema

`stack.yml` uses a strict schema:

```yaml
schema_version: "1.0"

stack:
  id: statsperform-playbook
  name: Stats Perform Playbook
  version: "1.0.0"
  kind: capability
  owner: statsperform
  description: Playbook UI/component/design-system stack for web apps

applies_to:
  archetypes:
    - web_app

provides:
  ui.components: playbook
  ui.tokens: playbook
  ui.forms: playbook-form-builder
  ui.icons: playbook-icons
  test.ui_accessibility: axe
  audit.design_system: playbook-cli

implies: []

requires:
  commands:
    - npx
  registries:
    - statsperform-nexus

tools:
  playbook_cli:
    command: npx -y @statsperform/playbook-cli
    purpose: component, token, icon, pattern, and compliance lookup

context:
  files:
    - context.md

conflicts:
  - capability: ui.components
    operator: "!="
    value: playbook
```

Required top-level keys:

- `schema_version`
- `stack`
- `applies_to`
- `provides`
- `context`

Supported `stack.kind` values:

- `archetype`: owns the default structure for a target kind.
- `capability`: owns a narrower concern such as UI components or logging.
- `policy`: owns governance or compliance constraints.

Capability keys use namespaced strings. Core namespaces are:

- `ui.*`
- `web_app.*`
- `service.*`
- `test.*`
- `lint.*`
- `typecheck.*`
- `delivery.*`
- `observability.*`
- `audit.*`
- `docs.*`
- `data.*`
- `messaging.*`
- `stream.*`
- `schema.*`

Unknown namespaces are invalid unless they start with `x.`. Extension keys
under `x.` are preserved in resolved output but ignored by core Echelon logic.

## Initial Stack Definitions

### statsperform-playbook

Kind: `capability`

Applies to: `web_app`

Provides:

```yaml
ui.components: playbook
ui.tokens: playbook
ui.forms: playbook-form-builder
ui.icons: playbook-icons
ui.scaffolding: playbook-guided
test.ui_accessibility: axe
test.visual: playwright
audit.design_system: playbook-cli
docs.ui_lookup: playbook-cli
```

Operational guidance:

- Use `@statsperform/playbook-cli` for component, style, icon, pattern, form
  builder, and compliance lookups.
- Use Playbook integration guidance when setting up React apps.
- Use Playbook compliance scans for design-system review.
- Add accessibility-oriented UI tests around Playbook component composition,
  without forcing a specific frontend test runner.
- Do not imply Stark.

### statsperform-msa-service

Kind: `archetype`

Applies to: `service`, `api_service`

Provides:

```yaml
service.template: caic-msa-service-template
service.core: caic-msa-core
service.framework: fastapi
service.runtime: uv-python
service.config: pydantic-settings
delivery.service: msa-template-default
test.backend: pytest
lint.python: ruff
typecheck.python: mypy
observability.service: msa-default
```

Operational guidance:

- Use the MSA service template for new backend services.
- Use MSA core conventions for service structure, configuration,
  observability, health checks, Docker, CI, and test/lint/typecheck commands.
- Select persistence, messaging, and stream-processing stacks separately when
  requirements call for them.
- Do not apply Stark delivery behavior to MSA services.

### statsperform-stark-webapp

Kind: `archetype`

Applies to: `web_app`

Provides:

```yaml
web_app.template: opta-stark
web_app.framework: nextjs
web_app.workspace: nx
web_app.runtime: node
delivery.web_app: stark-default
observability.web_app: stark-default
test.frontend: jest-rtl
```

Implies:

```yaml
implies:
  - statsperform-playbook
```

Operational guidance:

- Use Stark only for web-app targets.
- Stark may imply Playbook because the Stark template currently uses
  `@statsperform/react-playbook`.
- Stark does not imply MSA and is not a backend deployment model.

## Infrastructure Capability Stack Examples

Database, messaging, and stream-processing stacks are capability stacks. They
compose with application archetypes but do not define the application archetype
by themselves.

These examples define the shape Echelon should support. They do not need to be
bundled in the first implementation unless the organization has agreed
standards and context files for them.

### statsperform-postgres

Kind: `capability`

Applies to: `service`, `api_service`, `worker`

Provides:

```yaml
data.store: postgres
data.migrations: alembic
data.access: sqlalchemy
test.data: integration-postgres
```

Operational guidance:

- Use when requirements require relational persistence.
- Keep migration, local development, test fixture, and deployment guidance in
  the stack context.
- Do not imply MSA; a Postgres stack can compose with any compatible service
  archetype.

### statsperform-kafka

Kind: `capability`

Applies to: `service`, `api_service`, `worker`, `data_pipeline`

Provides:

```yaml
messaging.broker: kafka
messaging.consumer: kafka
messaging.producer: kafka
schema.registry: kafka-compatible
test.messaging: kafka-integration
```

Operational guidance:

- Use when requirements require event production or consumption.
- Capture topic ownership, consumer group, retry, dead-letter, schema, and
  local test-container guidance in context.
- Do not imply Flink; stream processing is a separate decision.

### statsperform-flink

Kind: `capability`

Applies to: `data_pipeline`, `worker`

Provides:

```yaml
stream.engine: flink
stream.state: flink-managed
stream.checkpointing: flink
test.stream: flink-integration
```

Operational guidance:

- Use when requirements require long-running stream processing, stateful
  operators, windowing, or event-time processing.
- Compose with Kafka or another messaging stack when the pipeline source/sink
  requires it.
- Do not apply to ordinary request/response services unless the architecture
  explicitly classifies the target as a stream-processing worker or pipeline.

## Resolution Flow

Before Phase A routing and before Phase B harness build prompts, Echelon runs a
stack resolver:

1. Read selected stack IDs from `.echelon/config.yml`, then legacy config if
   compatibility requires it.
2. Load bundled stack definitions from `extension/stacks/**/stack.yml` in source
   checkouts, or `.specify/extensions/echelon/stacks/**/stack.yml` in installed
   project checkouts.
3. Load optional project-local stack definitions from `.echelon/stacks/**/stack.yml`.
4. Resolve `implies` recursively.
5. Reject unknown, cyclic, or duplicate stack IDs.
6. Match selected stacks against known target archetypes when supplied by
   `stacks.target_archetypes` or spec frontmatter `target_archetypes`.
7. Merge `provides` into a resolved capability map.
8. Detect capability conflicts.
9. Surface missing commands, registries, or credentials as early warnings or
   blockers depending on phase.
10. Render deterministic stack context for orchestration and agent prompts.
11. Optionally persist `.echelon/context/stacks/resolved.yml` and
    `.echelon/context/stacks/resolved.md` when a phase needs runtime artifacts.

Stack resolution is deterministic. Agents consume only resolved context.

## Conflict Rules

Conflicts are detected before agent dispatch.

Hard conflicts:

- Two selected stacks provide different values for the same core capability
  without an explicit override.
- A stack is applied to an incompatible target archetype.
- A selected stack implies a stack that conflicts with another selected stack.
- A stack references missing context files.
- A target selects two stacks that provide different values for exclusive
  infrastructure capabilities, for example `data.store` or
  `messaging.broker`, without explicit override support.

Warnings:

- Required command is missing but the current phase is only planning.
- Required registry or credentials may be unavailable but no install/build
  operation is happening yet.
- A selected stack provides only `x.*` capabilities and no core capabilities.

Project config may allow explicit overrides later, but the initial design should
not include overrides. Failing fast is safer until real override cases exist.

## Generated Agent Context

`resolved.md` should be concise and structured:

```markdown
# Resolved Echelon Stacks

## Selected Stacks

- statsperform-playbook (implied by statsperform-stark-webapp)
- statsperform-stark-webapp

## Capabilities

| Capability | Value | Source |
|---|---|---|
| web_app.framework | nextjs | statsperform-stark-webapp |
| ui.components | playbook | statsperform-playbook |

## Mandatory Guidance

### Web App

- Use the Stark Nx/Next.js application structure.
- Use Playbook for UI components, tokens, forms, and icons.
- Use the Playbook CLI before selecting components or tokens.

## Requirements

- Requires Stats Perform Nexus npm registry access.

## Stack Guidance

### context.md

Resolved contents from each selected or implied stack context file.
```

Phase specs include this file where relevant:

- Architecture and planning phases use it for technology decisions.
- Sentinel/test strategy phases use it for stack-specific test defaults.
- Orchestrator/task phases use it for scaffolding and sequencing.
- Build implementation prompts append it to generated `Strategy Context`, after
  any strategy-file content.
- Review, test, visual, and compliance gates use it for stack-specific checks.

Agents must not read raw `stack.yml` files during ordinary execution. Raw stack
definitions are orchestration inputs, not agent prompt material.

## Architecture Components

Add a small deterministic stack subsystem:

```text
src/harness/stacks/
  __init__.py
  schema.py
  loader.py
  resolver.py
  renderer.py
  errors.py
```

Responsibilities:

- `schema.py`: dataclasses and validation for stack definitions and resolved
  output.
- `loader.py`: reads bundled and project-local stack definitions.
- `resolver.py`: implication resolution, archetype checks, capability merge,
  and conflict detection.
- `renderer.py`: renders `resolved.md`.
- `errors.py`: structured exceptions with user-facing messages.

This subsystem should not depend on LLM providers or agent files. It should be
usable from tests and CLI preflight code.

## Config Integration

Add config support:

```yaml
stacks:
  target_archetypes: []
  selected: []
```

Default is empty. Empty means no stack override.

`target_archetypes` is also optional. When present, it makes stack compatibility
validation explicit. Spec frontmatter may provide the same signal:

```yaml
---
target_archetypes:
  - web_app
---
```

Environment override can be added later if needed. The initial implementation
should keep selection in committed config to avoid hidden stack changes in CI.

## Error Handling

Unknown stack:

```text
Unknown Echelon stack: statsperform-foo
Available stacks: statsperform-playbook, statsperform-msa-service, statsperform-stark-webapp
```

Archetype mismatch:

```text
Stack statsperform-msa-service applies to service/api_service, but target web is web_app.
Select a service target or remove the stack from this target.
```

Capability conflict:

```text
Stack capability conflict:
  ui.components = playbook from statsperform-playbook
  ui.components = mui from example-mui

Remove one stack or define an explicit override after override support exists.
```

Missing requirement during build:

```text
Stack requirement unavailable:
  statsperform-playbook requires registry statsperform-nexus.

Configure Nexus access before running build, or remove statsperform-playbook.
```

## Testing Strategy

Unit tests:

- Load valid bundled stacks.
- Reject malformed stack definitions.
- Reject unknown selected stack IDs.
- Resolve implied stacks.
- Reject implication cycles.
- Merge compatible capabilities.
- Reject conflicting capabilities.
- Allow unknown `x.*` capabilities while preserving them.
- Reject unknown non-extension capability namespaces.
- Render stable `resolved.yml` and `resolved.md`.

Integration tests:

- Config with no stacks preserves current behavior.
- Config selecting Playbook generates Playbook context.
- Config selecting Stark implies Playbook.
- Config selecting MSA and Stark succeeds for multi-target service + web app
  scenarios when each stack applies to the correct target.
- Config selecting MSA for a web-only target fails early.
- Config selecting MSA plus Kafka or MSA plus Postgres composes when the target
  archetype is service/API/worker and capabilities do not conflict.
- Config selecting Flink for an ordinary web app or request/response service
  fails unless the target archetype includes `data_pipeline` or `worker`.

Prompt/contract tests:

- Phase specs reference resolved stack context, not individual stack names.
- Build prompt can receive resolved stack context without agent prose changes.

## Migration Plan

Initial migration is additive:

1. Add stack schema and resolver.
2. Add bundled stack definitions and context files.
3. Add config parsing for `stacks.selected`.
4. Generate resolved stack context during preflight/init.
5. Include resolved stack context in relevant phase context packs and build
   prompts.
6. Add validation tests.

Existing projects with no selected stacks are unaffected.

## Open Extension Model

Project-local stacks live under:

```text
.echelon/stacks/<stack-id>/stack.yml
.echelon/stacks/<stack-id>/context.md
```

Project-local stacks can add capabilities and context without changing Echelon
source. They cannot override bundled stack IDs in the initial design. This keeps
resolution deterministic and avoids supply-chain ambiguity.

If external stack distribution becomes important, add a signed stack package
mechanism later. Do not solve remote distribution in the first implementation.

## Acceptance Criteria

- Users can select `statsperform-playbook`, `statsperform-msa-service`, or
  `statsperform-stark-webapp` through Echelon config.
- With no selected stacks, Echelon behavior is unchanged.
- Stark implies Playbook; Playbook does not imply Stark.
- MSA and Stark are scoped to different archetypes and cannot be confused as a
  shared deployment profile.
- Database, messaging, and stream-processing choices are represented as
  independent capability stacks, not hidden defaults inside MSA.
- Stack conflicts are detected before agent dispatch.
- Agents receive generated resolved context, not stack-specific branching prose.
- New stacks can be added by adding a directory with `stack.yml` and
  `context.md`.
