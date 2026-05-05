# echelon.cicd — Design Spec

**Date:** 2026-04-27
**Status:** Draft

---

## Problem

`echelon-deploy` is a generic blue/green and CLI deployment system. It cannot automatically produce correct deployment artifacts (Dockerfile, `echelon-config.yml` deploy block, CI workflow) for arbitrary project stacks — especially pnpm monorepos, multi-app workspaces, or projects that evolve over time. Hard-coding detection heuristics in bash scripts is a dead end.

---

## Solution

`echelon.cicd` is a thin echelon command that commissions the full cognitive squad to **design and implement CI/CD** for the current project. The squad analyzes the project, reasons about the right pipeline shape, and generates the artifacts. The command itself contains no detection logic — it just constructs a well-engineered prompt and delegates to `echelon.run`.

This is intentionally self-referential: echelon configuring its own deployment infrastructure using its own intelligence.

---

## Command

**Name:** `echelon.cicd`
**Location:** `extension/commands/echelon.cicd.md`
**Invocation:** explicit
**Re-runnable:** yes — updates existing artifacts in-place

---

## Lifecycle Position

```
echelon.init       — bootstrap echelon-config.yml, install Traefik / git hook
echelon.cicd       — NEW: design + generate CI/CD for this project   ← here
echelon.run        — cognitive squad feature work
echelon.deploy     — manual deploy / status / rollback
post-merge hook    — auto-deploy on git merge
```

---

## What the Command Does

1. **Anchor** project root and extension path
2. **Construct prompt** — the static prompt template below (no pre-scraping)
3. **Delegate** — pass the prompt to `echelon.run` as the feature description

The command contains no heuristics and no context pre-gathering. SCOUT explores
the project as part of Tier 1 discovery, guided by `<analysis_steps>` in the
prompt. Pre-injecting a bash-scraped context block is redundant and fragile —
SCOUT finds what it needs more reliably than bash pattern matching.

---

## Prompt Template (Anthropic Best Practices)

The prompt passed to `echelon.run` follows Anthropic prompt engineering conventions:
- Role assignment first
- Task stated before constraints
- XML tags to delimit logical sections
- Explicit output format
- Constraints stated as positive rules, not negations where possible

```
You are a senior DevOps engineer and software architect.

<task>
Analyze this project and implement a CI/CD pipeline that integrates with the
installed echelon-deploy system for local blue/green (HTTP) or tag-pointer (CLI)
deployment.
</task>

<analysis_steps>
Think through the following before generating any files.
The examples given in each step are illustrative, not exhaustive.
For any ecosystem not listed, read its build manifests and apply the same
reasoning. If a stack is genuinely unfamiliar, state what you found and ask
before generating a Dockerfile.

1. Package manager — read all build manifests and lockfiles to identify the
   package manager (e.g. pnpm-lock.yaml → pnpm, package-lock.json → npm,
   yarn.lock → yarn, bun.lockb → bun, Cargo.lock → cargo, go.sum → go modules,
   requirements.txt / pyproject.toml → pip/poetry/uv, Gemfile.lock → bundler,
   pom.xml / build.gradle → maven/gradle, mix.lock → mix).
   Use each ecosystem's frozen-install command, never a generic fallback.

2. Project shape — single app vs monorepo. For monorepos:
   - Identify deployable apps (apps/ or packages/ with their own entry point)
   - Determine build context and target per app
   - One Dockerfile per deployable app

3. Framework and runtime — read entry points, dependencies, and config files to
   determine the correct base image and build pipeline. Examples: static SPA
   (Vite, CRA) → multi-stage + nginx; SSR (Next.js, Nuxt, SvelteKit) → node;
   API server (Express, Fastify, FastAPI, Django, Rails, Spring, Gin) → runtime
   image; compiled binary (Go, Rust, Elixir release) → multi-stage + minimal
   runtime image. For any other framework, derive the correct pattern from its
   documentation conventions.

4. Existing Dockerfiles — if a Dockerfile already exists, preserve its
   structure; only patch what is wrong (e.g. wrong package manager command).

5. Database dependencies — inspect dependency manifests for database drivers
   and ORMs (e.g. pg, mysql2, prisma, sequelize, typeorm, sqlalchemy, ecto,
   gorm, mongoose, redis, etc.) to identify required backing services.
   For each detected database:
   - Add a `services:` block to echelon-config.yml listing the container image,
     network alias, volume mount for persistence, and environment variables.
   - Generate a `scripts/bash/db-start.sh` script that starts each service
     container on the speckit-deploy Docker network (idempotent: skip if
     already running). Database containers are not blue/green — they run
     continuously alongside the app.
   - Inject the correct DATABASE_URL / connection env vars into the app
     container at deploy time via the deploy block.

6. Deploy type — http (web server, needs ports) vs cli (binary, needs
   health_check command). Infer from project type; confirm against existing
   echelon-config.yml deploy block if present.

7. Test setup — detect test runner and existing test scripts for the CI
   workflow (e.g. jest, vitest, pytest, go test, cargo test, rspec, mix test).
</analysis_steps>

<deliverables>
Generate exactly these artifacts:

1. **Dockerfile** (or one per app in a monorepo) — correct for detected stack,
   correct package manager, correct build context. Place at project root or
   apps/{name}/Dockerfile as appropriate.

2. **echelon-config.yml deploy block** — update the existing deploy: section in-place.
   Set type, dockerfile (path relative to project root), blue_port / green_port
   (HTTP) or health_check / install_path (CLI). If databases were detected, add
   a services: block. Do not touch other sections.

3. **scripts/bash/db-start.sh** — only if database services were detected.
   Starts each backing service container on the speckit-deploy network.
   Idempotent: skips containers that are already running.

4. **.github/workflows/ci.yml** — runs on every push and pull_request to main.
   Jobs: install dependencies, lint (if configured), run tests.
   No remote deploy step. echelon-deploy handles local CD via git post-merge hook.
</deliverables>

<constraints>
- All generated files must be idempotent: re-running echelon.cicd on an evolved
  project updates existing files rather than duplicating content.
- The Dockerfile must build successfully with `docker build` from the project root.
- The CI workflow must use the same package manager detected in step 1.
- Do not generate a docker-compose.yml — echelon-deploy uses plain Docker + Traefik.
- Do not add a deploy job to the CI workflow — local CD is handled by the
  post-merge git hook installed by echelon.init.
- Database containers run on the speckit-deploy network alongside the app —
  they are not managed by Traefik and do not get blue/green slots.
</constraints>
```

---

## Output Artifacts

| Artifact | Condition | Created / Updated |
| --- | --- | --- |
| `Dockerfile` or `apps/*/Dockerfile` | always | Created if absent; patched if wrong |
| `echelon-config.yml` `deploy:` block | always | Updated in-place |
| `scripts/bash/db-start.sh` | database detected | Created if absent; updated if present |
| `.github/workflows/ci.yml` | always | Created if absent; updated if present |

---

## Out of Scope

- Remote deployment (addressed separately)
- Registry push / image publishing
- docker-compose setup
- Multi-environment config (staging, production)
- Self-hosted runner configuration
- Database migrations (app concern, not CI/CD concern)
- CI services block for test databases (addressed with remote CI separately)

---

## Open Questions

None — scope is locked.
