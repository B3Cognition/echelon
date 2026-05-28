---
name: speckit.echelon.cicd
description: "Design and implement CI/CD for this project — Dockerfile, echelon-config.yml deploy block, GitHub Actions CI workflow, and db-start.sh if databases are detected."
behavior:
  invocation: automatic
---

## Role

You are ORCHESTRATOR setting up CI/CD for this project. Your job is to construct
the feature description below and commission the full echelon cognitive squad to
design and implement all CI/CD artifacts.

---

## User Input

$ARGUMENTS

---

## Overview

`echelon.cicd` delegates all project analysis and artifact generation to the
full cognitive squad via `speckit.echelon.run`. The command itself contains no
stack-detection heuristics — speckit-echelon-scout (SCOUT) explores the project and the squad reasons
about the correct pipeline shape.

Re-runnable: safe to run again when the project evolves. All generated artifacts
are always updated in-place, never duplicated.

---

## Step 1: Run the cognitive squad

Invoke the `speckit-echelon-run` skill with the feature description below as `$ARGUMENTS`.

If the user provided input in `$ARGUMENTS` (e.g. "focus on the API app"), append it after the closing `</constraints>` tag as:

```xml
<user_context>
{user input here}
</user_context>
```

Always pass the hardcoded feature description verbatim — do not summarise or rewrite it.

---

**Feature description to pass:**

```text
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
   Always use each ecosystem's frozen-install command, never a generic fallback.

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
   - Add a services: block to echelon-config.yml listing the container image,
     network alias, volume mount for persistence, and environment variables.
   - Generate the file at `$(git rev-parse --show-toplevel)/scripts/bash/db-start.sh`
     — this is a project-owned script, NOT an echelon extension file. It must
     always be written under project `scripts/bash/`, never inside `.specify/`.
     The correct path looks like
     `myproject/scripts/bash/db-start.sh`, not
     `myproject/.specify/extensions/echelon/scripts/bash/db-start.sh`.
     The script starts each service container on the speckit-deploy Docker
     network (idempotent: skip if already running). Database containers are not
     blue/green — they run continuously alongside the app.
   - Inject the correct DATABASE_URL / connection env vars into the app
     container at deploy time via the deploy block.

6. Deploy type — http (web server, needs ports) vs cli (binary, needs
   health_check command). Infer from project type; confirm against existing
   echelon-config.yml deploy block if present.

7. Test setup — detect test runner and existing test scripts for the CI
   workflow (e.g. jest, vitest, pytest, go test, cargo test, rspec, mix test).

8. Default branch — detect the repository's default branch name:

   git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'

   Fall back to `git symbolic-ref --short HEAD` if the remote check fails.
   Always use the detected branch name in the CI workflow triggers. Do not hardcode `main`.

9. Container listen port — detect the port the application actually listens on
   inside the container. Read the Dockerfile EXPOSE directive first; if absent or
   unclear, read framework config files (e.g. next.config.js, .env, server.js,
   main.py, config.ru). Examples: Next.js custom port in next.config.js or
   `server.listen(PORT)` → use that value; Express with `app.listen(3000)` → 3000;
   nginx static site → 80; FastAPI/uvicorn → 8000; Rails → 3000; Go net/http → 8080.
   Set `container_port: <detected>` in the echelon-config.yml deploy block.
   Default to 80 only for static sites served by nginx/caddy.
   This value is used by deploy.sh to wire Traefik's load balancer and the
   health-check port binding — a wrong value causes deploy failures.

10. Env file location — for monorepos, the deployable app's .env.local (or
    equivalent) is typically NOT at the project root but inside the app directory
    (e.g. apps/web/.env.local). If such a file exists, set
    `build_env_file: <relative-path>` in the echelon-config.yml deploy block so deploy.sh
    passes the correct build args to docker build. Always document only the path;
    do not commit secrets. The file itself is gitignored. If the env file is at the
    project root, omit build_env_file (deploy.sh finds .env.local automatically).

11. Health check path — determine whether the app exposes a dedicated health
    endpoint (e.g. /api/health, /healthz, /ping) that returns 2xx when the app
    is fully operational. If one exists or can be added cheaply (a one-line route
    handler), set `health_check_path: /api/health` in the echelon-config.yml deploy
    block. This enables strict 2xx health checks on deploy, catching broken
    bundles and misconfigured apps (e.g. SSG pages that crash at runtime) before
    the live slot is swapped. If no health endpoint exists and adding one is out
    of scope, omit health_check_path — deploy.sh falls back to a permissive
    "server is up" check.
</analysis_steps>

<deliverables>
Generate exactly these artifacts:

1. Dockerfile (or one per app in a monorepo) — correct for detected stack,
   correct package manager, correct build context. Place at project root or
   apps/{name}/Dockerfile as appropriate.

2. echelon-config.yml deploy block — update the existing deploy: section in-place.
   Set type, dockerfile (path relative to project root), blue_port / green_port
   (HTTP) or health_check / install_path (CLI), and container_port (detected in
   step 9). If databases were detected, add a services: block. Always preserve
   other sections; do not touch other
   sections. If `echelon-config.yml` does not exist, create it with a minimal skeleton
   containing only the `deploy:` block with detected values.

3. `$(git rev-parse --show-toplevel)/scripts/bash/db-start.sh` — only if
   database services were detected. This is a project-owned script; write it
   at the git repository root under `scripts/bash/`, never inside `.specify/`.
   Starts each backing service container on the speckit-deploy network.
   Idempotent: skips containers that are already running.

4. echelon-config.yml verify_command — add `verify_command: <command>` to the
   existing echelon-config.yml based on the test runner detected in step 7.
   Use the simplest correct invocation:
   - Python (pytest):    `pytest`
   - Python (uv):        `uv run pytest`  (when uv.lock is present)
   - Node (pnpm):        `pnpm test`
   - Node (yarn):        `yarn test`
   - Node (npm):         `npm test`
   - Go:                 `go test ./...`
   - Rust:               `cargo test`
   - Swift (SPM):        `swift test` or `swift test --package-path <subdir>`
                          (use --package-path when Package.swift is not at root)
   - Ruby:               `bundle exec rspec`
   - Java/Gradle:        `./gradlew test`
   - Java/Maven:         `./mvnw test`
   Always leave an existing verify_command unchanged. Do NOT add verify_command if
   it is already set. Do NOT change other sections. Do NOT write an absolute path
   — the harness runs the command from the project root.

5. .github/workflows/ci.yml — runs on every push and pull_request to the default branch (detected in step 8).
   Jobs: install dependencies, lint (if configured), run tests.
   No remote deploy step. echelon-deploy handles local CD via git post-merge hook.

   The generated workflow MUST include the following at the top of the file as a
   YAML comment block, and as the first step of the first job:

   Comment block (top of file, after the `on:` trigger):
   ```yaml
   # NOTE: echelon harness already builds and verifies this project in a clean
   # Docker sandbox (build + tests + security scan + license check) before the
   # PR is opened. This CI workflow may be replaceable with a lightweight
   # verification flow (security scan + license check only).
   # See: echelon.cicd spec — docs/superpowers/specs/2026-04-27-echelon-cicd-design.md
   ```

   First step of the first job:
   ```yaml
   - name: ⚠ CI scope note
     run: |
       echo "NOTE: echelon harness already verified this build in Docker (tests + security + licenses)."
       echo "Consider replacing this workflow with a lightweight verification flow."
   ```
</deliverables>

<constraints>
- All generated files must be idempotent: re-running echelon.cicd on an evolved
  project updates existing files rather than duplicating content.
- echelon-config.yml MUST be updated in-place. If a deploy: block already exists, patch
  only the fields that need correction (container_port, health_check_path,
  build_env_file, services). Always preserve echelon.init-owned deploy fields.
  Do NOT change the dockerfile, blue_port, green_port,
  or the app being deployed — those were set by echelon.init and are authoritative.
  Do NOT create a new echelon-config.yml or overwrite the file wholesale.
- verify_command MUST be a top-level key in echelon-config.yml (not nested under
  deploy: or any other section). Always preserve an existing verify_command; do
  not add it if it is already present.
- The Dockerfile must build successfully with docker build from the project root.
- The CI workflow must use the same package manager detected in step 1.
- Always target plain Docker + Traefik; do not generate a docker-compose.yml.
- Always leave CD to the local post-merge hook; do not add a deploy job to the
  CI workflow.
- Database containers run on the speckit-deploy network alongside the app —
  always keep them outside Traefik; they are not managed by Traefik and do not
  get blue/green slots.
</constraints>
```
