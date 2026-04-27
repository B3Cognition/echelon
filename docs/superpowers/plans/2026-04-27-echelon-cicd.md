# echelon.cicd Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `speckit.echelon.cicd` — a command that uses the full echelon cognitive squad to design and implement CI/CD artifacts (Dockerfile, echelon.yml deploy block, db-start.sh, GitHub Actions workflow) for any project stack.

**Architecture:** A thin command file that constructs a well-engineered Anthropic-style prompt and delegates to `speckit.echelon.run`. The command contains zero detection heuristics — all reasoning lives in SCOUT and the squad. Registered in `extension.yml` like all other commands.

**Tech Stack:** Markdown command file, YAML extension manifest. No new code.

---

## File Map

| File | Action | Purpose |
| --- | --- | --- |
| `extension/commands/echelon.cicd.md` | Create | The command COMMANDER reads and executes |
| `extension/extension.yml` | Modify | Register the new command under `provides.commands` |

---

### Task 1: Create the command file

**Files:**
- Create: `extension/commands/echelon.cicd.md`

- [ ] **Step 1: Create the file with this exact content**

```markdown
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

## Step 1: Anchor

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel)
echo "PROJECT_ROOT=${PROJECT_ROOT}"
```

If this fails (not a git repo), report the error and stop.

---

## Step 2: Run the cognitive squad

Invoke `speckit.echelon.run` with the following feature description as
`$ARGUMENTS`. Pass it verbatim — do not summarise or rewrite it.

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
</analysis_steps>

<deliverables>
Generate exactly these artifacts:

1. Dockerfile (or one per app in a monorepo) — correct for detected stack,
   correct package manager, correct build context. Place at project root or
   apps/{name}/Dockerfile as appropriate.

2. echelon.yml deploy block — update the existing deploy: section in-place.
   Set type, dockerfile (path relative to project root), blue_port / green_port
   (HTTP) or health_check / install_path (CLI). If databases were detected, add
   a services: block. Do not touch other sections.

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
```

- [ ] **Step 2: Verify the file exists**

```bash
ls -la /path/to/echelon/extension/commands/echelon.cicd.md
```

Expected: file present, non-zero size.

- [ ] **Step 3: Commit**

```bash
git add extension/commands/echelon.cicd.md
git commit -m "feat(cicd): add speckit.echelon.cicd command"
```

---

### Task 2: Register the command in extension.yml

**Files:**
- Modify: `extension/extension.yml` (in the `provides.commands` list, after `speckit.echelon.deploy`)

- [ ] **Step 1: Add the registration entry**

In `extension/extension.yml`, locate the `speckit.echelon.deploy` entry (around line 140) and insert the following immediately after it:

```yaml
    - name: "speckit.echelon.cicd"
      file: "commands/echelon.cicd.md"
      description: "Design and implement CI/CD for this project — Dockerfile, echelon.yml deploy block, GitHub Actions CI, and database services if detected. Re-runnable."
      behavior:
        execution: isolated
        invocation: explicit
        capability: strong
        effort: high
        tools: full
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('extension/extension.yml')); print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add extension/extension.yml
git commit -m "feat(cicd): register speckit.echelon.cicd in extension manifest"
```

---

### Task 3: Sync to installed copy and smoke test

The extension must be installed in the target project for the command to be available. The installed copy lives at `{project}/.specify/extensions/echelon/`.

- [ ] **Step 1: Copy command file to the installed copy in the test project**

```bash
# Replace with the actual project path where you want to test
TARGET_PROJECT=/Users/michalbachorik/work/animacure

cp extension/commands/echelon.cicd.md \
   "${TARGET_PROJECT}/.specify/extensions/echelon/commands/echelon.cicd.md"

echo "copied"
```

Expected: `copied`

- [ ] **Step 2: Verify the installed command is registered**

The installed `extension.yml` also needs the entry. Either run `specify extension update` in the target project, or copy the manifest:

```bash
cp extension/extension.yml \
   "${TARGET_PROJECT}/.specify/extensions/echelon/extension.yml"

python3 -c "
import yaml
d = yaml.safe_load(open('${TARGET_PROJECT}/.specify/extensions/echelon/extension.yml'))
names = [c['name'] for c in d['provides']['commands']]
assert 'speckit.echelon.cicd' in names, 'not found'
print('registered ok')
"
```

Expected: `registered ok`

- [ ] **Step 3: Verify echelon.init has been run in the test project**

```bash
test -f "${TARGET_PROJECT}/.specify/squad/deploy-state.json" && echo "init ok" || echo "run echelon.init first"
```

If `init ok`: proceed. If not: run `speckit.echelon.init` in the target project first.

- [ ] **Step 4: Run the command**

Open Claude Code in `${TARGET_PROJECT}` and run:

```
/speckit.echelon.cicd
```

- [ ] **Step 5: Verify outputs**

After the squad completes, check each expected artifact exists and looks correct:

```bash
cd "${TARGET_PROJECT}"

# Dockerfile
test -f Dockerfile && echo "✓ Dockerfile" || echo "✗ Dockerfile missing"

# echelon.yml deploy block
grep -q 'deploy:' echelon.yml && echo "✓ deploy block" || echo "✗ deploy block missing"

# GitHub Actions workflow
test -f .github/workflows/ci.yml && echo "✓ ci.yml" || echo "✗ ci.yml missing"

# db-start.sh (only if DB dependencies detected)
test -f scripts/bash/db-start.sh && echo "✓ db-start.sh" || echo "  (no db-start.sh — expected if no DB deps)"
```

- [ ] **Step 6: Verify Dockerfile builds**

```bash
cd "${TARGET_PROJECT}"
docker build -t cicd-smoke-test . && echo "✓ build ok" || echo "✗ build failed"
docker rmi cicd-smoke-test 2>/dev/null
```

Expected: `✓ build ok`

- [ ] **Step 7: Commit the test project artifacts**

```bash
cd "${TARGET_PROJECT}"
git add Dockerfile echelon.yml .github/workflows/ci.yml
git add scripts/bash/db-start.sh 2>/dev/null || true
git commit -m "chore: add CI/CD artifacts via echelon.cicd"
```
