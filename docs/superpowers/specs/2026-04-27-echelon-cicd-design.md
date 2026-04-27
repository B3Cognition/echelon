# echelon.cicd — Design Spec

**Date:** 2026-04-27
**Status:** Draft

---

## Problem

`echelon-deploy` is a generic blue/green and CLI deployment system. It cannot automatically produce correct deployment artifacts (Dockerfile, `echelon.yml` deploy block, CI workflow) for arbitrary project stacks — especially pnpm monorepos, multi-app workspaces, or projects that evolve over time. Hard-coding detection heuristics in bash scripts is a dead end.

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
echelon.init       — bootstrap echelon.yml, install Traefik / git hook
echelon.cicd       — NEW: design + generate CI/CD for this project   ← here
echelon.run        — cognitive squad feature work
echelon.deploy     — manual deploy / status / rollback
post-merge hook    — auto-deploy on git merge
```

---

## What the Command Does

1. **Anchor** project root and extension path
2. **Gather context** — snapshot of key project signals (directory tree depth-2, `package.json` / `pyproject.toml` / `go.mod` presence, existing Dockerfiles, `echelon.yml` deploy block, git remote)
3. **Construct prompt** — assemble the feature description using the gathered context and the prompt template below
4. **Delegate** — pass the prompt to `echelon.run` as the feature description

The command contains no heuristics. All reasoning lives in the squad.

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

<project_context>
{{CONTEXT_BLOCK}}
</project_context>

<analysis_steps>
Think through the following before generating any files:

1. Package manager — detect npm / pnpm / yarn / bun from lockfile presence.
   For pnpm: use `pnpm install --frozen-lockfile`, not `npm ci`.

2. Project shape — single app vs monorepo. For monorepos:
   - Identify deployable apps (apps/ or packages/ with their own start script)
   - Determine build context and target per app
   - One Dockerfile per deployable app

3. Framework — detect Vite/React (static → nginx), Next.js (SSR → node),
   Express/Fastify (node server), FastAPI/Django (python), Go binary.
   Choose the correct base image and build pipeline for each.

4. Existing Dockerfiles — if a Dockerfile already exists, preserve its
   structure; only patch what is wrong (e.g. wrong package manager command).

5. Deploy type — http (web server, needs ports) vs cli (binary, needs
   health_check command). Infer from project type; confirm against existing
   echelon.yml deploy block if present.

6. Test setup — detect test runner (jest, vitest, pytest, go test) and
   existing test scripts for the CI workflow.
</analysis_steps>

<deliverables>
Generate exactly these artifacts:

1. **Dockerfile** (or one per app in a monorepo) — correct for detected stack,
   correct package manager, correct build context. Place at project root or
   apps/{name}/Dockerfile as appropriate.

2. **echelon.yml deploy block** — update the existing deploy: section in-place.
   Set type, dockerfile (path relative to project root), blue_port / green_port
   (HTTP) or health_check / install_path (CLI). Do not touch other sections.

3. **.github/workflows/ci.yml** — runs on every push and pull_request to main.
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
</constraints>
```

---

## Context Block Construction

The command gathers this context before injecting `{{CONTEXT_BLOCK}}`:

```bash
# Directory tree (depth 2, excluding node_modules/.git/.specify)
find . -maxdepth 2 -not -path '*/.git/*' -not -path '*/node_modules/*' \
       -not -path '*/.specify/*' | sort

# Package manager signals
ls package.json pnpm-lock.yaml package-lock.json yarn.lock bun.lockb \
   pyproject.toml requirements.txt go.mod 2>/dev/null

# Existing Dockerfiles
find . -name 'Dockerfile*' -not -path '*/.git/*' 2>/dev/null

# Existing echelon.yml deploy block
grep -A 10 '^deploy:' echelon.yml 2>/dev/null || echo "(no deploy block)"

# Git remote
git remote get-url origin 2>/dev/null || echo "(no remote)"
```

---

## Output Artifacts

| Artifact | Created / Updated |
|---|---|
| `Dockerfile` or `apps/*/Dockerfile` | Created if absent; patched if wrong |
| `echelon.yml` `deploy:` block | Updated in-place |
| `.github/workflows/ci.yml` | Created if absent; updated if present |

---

## Out of Scope

- Remote deployment (addressed separately)
- Registry push / image publishing
- docker-compose setup
- Multi-environment config (staging, production)
- Self-hosted runner configuration

---

## Open Questions

None — scope is locked.
