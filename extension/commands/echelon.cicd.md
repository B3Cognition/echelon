---
name: speckit.echelon.cicd
description: "Design and implement CI/CD for this project — Dockerfile, echelon.yml deploy block, GitHub Actions CI workflow, and db-start.sh if databases are detected."
behavior:
  invocation: explicit
---

## Role

You are COMMANDER setting up CI/CD for this project. Your job is to construct
the feature description below and commission the full echelon cognitive squad to
design and implement all CI/CD artifacts.

---

## User Input

$ARGUMENTS

---

## Overview

`echelon.cicd` delegates all project analysis and artifact generation to the
full cognitive squad via `speckit.echelon.run`. The command itself contains no
stack-detection heuristics — SCOUT explores the project and the squad reasons
about the correct pipeline shape.

Re-runnable: safe to run again when the project evolves. All generated artifacts
are updated in-place, never duplicated.

---

## Step 1: Run the cognitive squad

Invoke `speckit.echelon.run` with the feature description below as `$ARGUMENTS`.

If the user provided input in `$ARGUMENTS` (e.g. "focus on the API app"), append it after the closing `</constraints>` tag as:

```xml
<user_context>
{user input here}
</user_context>
```

Pass the hardcoded feature description verbatim — do not summarise or rewrite it.

---

**Feature description to pass:**

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
   - Add a services: block to echelon.yml listing the container image,
     network alias, volume mount for persistence, and environment variables.
   - Generate a scripts/bash/db-start.sh script that starts each service
     container on the speckit-deploy Docker network (idempotent: skip if
     already running). Database containers are not blue/green — they run
     continuously alongside the app.
   - Inject the correct DATABASE_URL / connection env vars into the app
     container at deploy time via the deploy block.

6. Deploy type — http (web server, needs ports) vs cli (binary, needs
   health_check command). Infer from project type; confirm against existing
   echelon.yml deploy block if present.

7. Test setup — detect test runner and existing test scripts for the CI
   workflow (e.g. jest, vitest, pytest, go test, cargo test, rspec, mix test).

8. Default branch — detect the repository's default branch name:

   git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'

   Fall back to `git symbolic-ref --short HEAD` if the remote check fails.
   Use the detected branch name in the CI workflow triggers. Do not hardcode `main`.
</analysis_steps>

<deliverables>
Generate exactly these artifacts:

1. Dockerfile (or one per app in a monorepo) — correct for detected stack,
   correct package manager, correct build context. Place at project root or
   apps/{name}/Dockerfile as appropriate.

2. echelon.yml deploy block — update the existing deploy: section in-place.
   Set type, dockerfile (path relative to project root), blue_port / green_port
   (HTTP) or health_check / install_path (CLI). If databases were detected, add
   a services: block. Do not touch other sections. If `echelon.yml` does not exist, create it with a minimal skeleton containing only the `deploy:` block with detected values.

3. scripts/bash/db-start.sh — only if database services were detected.
   Starts each backing service container on the speckit-deploy network.
   Idempotent: skips containers that are already running.

4. .github/workflows/ci.yml — runs on every push and pull_request to main.
   Jobs: install dependencies, lint (if configured), run tests.
   No remote deploy step. echelon-deploy handles local CD via git post-merge hook.
</deliverables>

<constraints>
- All generated files must be idempotent: re-running echelon.cicd on an evolved
  project updates existing files rather than duplicating content.
- The Dockerfile must build successfully with docker build from the project root.
- The CI workflow must use the same package manager detected in step 1.
- Do not generate a docker-compose.yml — echelon-deploy uses plain Docker + Traefik.
- Do not add a deploy job to the CI workflow — local CD is handled by the
  post-merge git hook installed by echelon.init.
- Database containers run on the speckit-deploy network alongside the app —
  they are not managed by Traefik and do not get blue/green slots.
</constraints>
```
