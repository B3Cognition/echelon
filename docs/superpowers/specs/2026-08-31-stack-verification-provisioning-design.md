# Stack Verification Provisioning Design

**Date:** 2026-08-31  
**Status:** proposed

## Problem

A selected stack can require infrastructure for verification, but current stack
metadata only describes commands, tools, and conceptual guidance. Delivery can
therefore enter an expensive implementation/repair loop even though its verify
command requires an unavailable service, such as PostgreSQL. Existing runtime
detection can start Compose only when a repository already contains a Compose
file; it cannot declare, generate, or validate the missing dependency.

## Goals

- Let a stack declare verification-only service dependencies.
- Report missing provisioning before a delivery loop begins.
- Generate reviewable, target-local local-development artifacts without
  starting containers or changing an existing Compose file.
- Support either generated local Compose or an externally supplied isolated
  connection URL.
- Make the mechanism reusable for PostgreSQL, Redis, queues, and other future
  verification services.

## Non-goals

- Production deployment, credentials, cloud resource creation, or CI/CD
  orchestration.
- Automatically starting, stopping, or deleting containers.
- Inferring an application-specific data model or mutating its migrations.
- Replacing a project-owned Compose configuration.

## Contract

Stack schema version 1.1 adds an optional `provisioning` list. Each provisioner
has a stable id, a `verification` scope, required environment variable(s), a
readiness probe, and one or more satisfiers. A satisfier is either an external
environment value or a deterministic template generator.

`game-persistence-postgres` will declare one `postgres-verify` provisioner:

```yaml
provisioning:
  - id: postgres-verify
    scope: verification
    services:
      - postgres
    environment:
      required:
        - DATABASE_URL
    readiness:
      command: pg_isready
    satisfiers:
      - kind: environment
        variable: DATABASE_URL
      - kind: compose-template
        output: docker-compose.echelon-verify.yml
        env_example: .env.echelon-verify.example
```

The schema accepts future provisioner kinds, but the first implementation only
supports `environment` and `compose-template`.

## Commands and user experience

`echelon stack preflight` resolves selected stacks and reports each provisioner
as `ready`, `prepared`, or `missing` in addition to existing command/tool
findings. It treats an explicitly supplied required environment variable as
ready. A generated compose file is prepared, not ready, because Echelon does
not start containers or claim a service is reachable.

`echelon stack provision [--stack <id>] [--target <path>]` renders missing
compose-template satisfiers into the selected implementation target. It:

- writes only `docker-compose.echelon-verify.yml` and
  `.env.echelon-verify.example`;
- refuses to overwrite existing generated files unless `--force` is supplied;
- does not execute Docker, alter a project-owned Compose file, or write secrets;
- prints the manual `docker compose`, `DATABASE_URL`, readiness, verification,
  and cleanup commands.

The output files are intended for user review and source control. Their names
make their verification-only purpose explicit and avoid collision with
`docker-compose.yml`.

## Delivery behavior

Before delivery starts or resumes a stack-dependent target, Echelon evaluates
the resolved provisioning contract. A missing provisioner blocks before the
LLM/build loop and reports the exact `stack provision` command. A prepared
Compose file still asks the user to run it manually or provide an isolated
external URL. Delivery never calls Docker on the user’s behalf.

The gate is target-scoped: in a multi-target workspace one target’s missing
database cannot prevent unrelated targets from running.

## Implementation boundaries

- `harness.stacks.schema`: parse and validate provisioner declarations.
- `harness.stacks.resolver`: carry resolved provisioners and their owning stack.
- `harness.stacks.provisioning`: pure detection, template rendering, and
  result/report types.
- `harness.stacks.preflight`: render deterministic provisioning findings.
- `echelon.cli` / Typer adapter: expose `stack provision` and invoke the
  target-scoped preflight gate from delivery entry points.
- `runtime/stacks/game-persistence-postgres`: declares the PostgreSQL template
  and its contract.

## Safety and failure handling

All generation stays below the explicit target root. Output paths are fixed
relative paths validated against directory traversal. Existing output files
are never overwritten without `--force`. A malformed stack provisioner is a
stack-validation error; a missing Docker CLI or unavailable `pg_isready` is a
preflight error with manual remediation. Status/preflight remain read-only.

## Verification

- Schema validation tests reject malformed provisioner declarations.
- Resolver tests preserve implied-stack provisioners and owner attribution.
- Provisioner tests cover rendering, no-overwrite behavior, external URL
  satisfaction, and target-path containment.
- CLI tests cover `stack provision`, preflight reporting, and target selection.
- Delivery tests prove a missing PostgreSQL provisioner blocks before invoking
  an LLM, and an explicit isolated `DATABASE_URL` permits delivery to proceed.
