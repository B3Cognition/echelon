---
description: "Run the harness loop for a spec: build on host + verify in Docker + push to feature branch"
behavior:
  invocation: explicit
---

## Role

You are ORCHESTRATOR running the harness loop for a spec: build on host, verify in Docker, and push to the feature branch.

---

## User Input

$ARGUMENTS

---

## Overview

Runs the harness loop for a spec. Architecture:

- **Build / Feedback** — executed by the LLM on the host (strategy `default` uses `echelon.build`; strategy `codegen` uses the SOAR pipeline via `speckit.echelon.codegen`)
- **Verification** — test suite runs inside a Docker sandbox (deterministic, isolated)
- **GitOps** — harness commits and pushes to the echelon feature branch; opens/updates the PR

The harness works **on the echelon feature branch** (e.g., `001-weather-dashboard`), not on a separate `harness/*` branch. This keeps all implementation history on the same branch that echelon created, so the PR to `main` is a single coherent branch.

Requires `harness.init` to have been run first.

---

## Environment Variables (injected by harness)

**`HARNESS_BUILD_STATUS_FILE`** — Path where the build skill writes its outcome JSON
(`{"status":"done"}` or `{"status":"impasse",...}`). Set only when running under harness —
use as the harness-mode signal.

**`HARNESS_SOURCE_DIR`** — Absolute path to the harness Python source (`src/harness/`).
If you need to understand harness internals (e.g., why verify failed), read files there
directly — do NOT search the filesystem. Key files: `ralph.py` (outer/inner loop),
`gitops.py` (git ops), `config.py` (config schema).

---

## Step 1: Check Initialized

```bash
test -f .specify/extensions/echelon/echelon-config.yml && echo "ok" || echo "missing"
```

If the output is `missing`, report:

**"Harness not initialized. Run `speckit.echelon.harness-init` first."** and stop immediately.

**ABSOLUTE RULE: Always stop with the message above when config is absent.** Do NOT create, recreate, or bootstrap `echelon-config.yml` (harness: section) yourself. Do NOT create `.specify/extensions/echelon/` or any subdirectory. Do NOT work around the missing config in any way. The config is owned by `harness.init` — any other path corrupts harness state.

---

## Step 2: Parse Intent

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spec_id` | — | Required. The spec to run (e.g., `001`). |
| `mode` | `semi` | `banzai` \| `semi` \| `guided` |
| `max_outer` | `3` | Max build→verify→feedback cycles |
| `auto_merge` | `true` | Merge PR automatically on convergence |
| `strategy` | `default` | `default` \| `codegen` — which build engine to use for Step 5 |

If `spec_id` is missing, ask: **"Which spec? Provide a spec ID (e.g., `001`)."** and stop.

Recognised `strategy` patterns in `$ARGUMENTS`: `strategy=codegen`, `strategy=default`. Anything not recognised defaults to `default`.

Locate the spec directory: find `specs/{spec_id}-*/` (e.g., `specs/001-weather-dashboard/`). If not found, report: **"Spec `{spec_id}` not found in `specs/`."** and stop.

Extract `{spec_name}` from the directory name (e.g., `weather-dashboard` from `001-weather-dashboard`).

---

## Step 3: Detect Feature Branch

Find the echelon feature branch for this spec. The feature branch was created by `speckit.echelon.run` and is named after the spec directory (e.g., `001-weather-dashboard`).

```bash
PYTHONPATH=.specify/extensions/echelon python -m harness gitops find-branch '{spec_id}'
```

- If a feature branch is found (e.g., `001-weather-dashboard`): use it as `{feature_branch}`. The worktree will be checked out on this branch, and all commits will land here.
- If not found: warn — **"No echelon feature branch found for spec `{spec_id}`. Expected a branch named `{spec_id}-*`. Run `speckit.echelon.run` first, or the harness will fall back to branching from `main`."** — and set `{feature_branch}` to empty string (legacy mode).

---

## Step 4: Create Harness Worktree

```bash
PYTHONPATH=.specify/extensions/echelon python -m harness gitops create-worktree \
  '{spec_id}' '{strategy}' 0 --base-branch '{feature_branch}'
```

`--base-branch` accepts an empty string — if `{feature_branch}` is empty, `create-worktree` treats it as `None` and uses legacy mode (new `harness/*` branch from `main`).

If this fails, report the error and stop.

The worktree is a checkout of the feature branch. All build output goes into the worktree. The project working directory (CWD) is read-only from this point forward — **always use the worktree path or the Python gitops API for git operations; never run git commands against CWD, never cherry-pick, never merge, never commit in CWD**.

After creating the worktree, sync any spec files present in CWD but missing from the worktree (e.g., `coverage-map.md` written by echelon but not yet committed to the branch):

```bash
SPEC_DIR="specs/{spec_id}-{spec_name}"
for f in $(ls "${SPEC_DIR}/" 2>/dev/null); do
  if [ ! -f "{worktree_path}/${SPEC_DIR}/${f}" ]; then
    mkdir -p "{worktree_path}/${SPEC_DIR}"
    cp "${SPEC_DIR}/${f}" "{worktree_path}/${SPEC_DIR}/${f}"
  fi
done
```

This ensures the worktree has the full spec context without any git cherry-pick.

---

## Step 4b: Apply Deployment Context to Worktree

Before building, read the deployment configuration from CWD (not the worktree) to understand the app's subpath:

```bash
PYTHONPATH=.specify/extensions/echelon python3 -c "
import json, pathlib, sys
p = pathlib.Path('.specify/squad/deploy-state.json')
if not p.exists():
    print('none none')
    sys.exit(0)
try:
    d = json.loads(p.read_text())
    print(d.get('app', '') or 'none', d.get('type', '') or 'none')
except Exception as e:
    print(f'ERROR reading deploy-state.json: {e}', file=sys.stderr)
    sys.exit(1)
"
```

Capture the two space-separated tokens: first is `DEPLOY_APP_NAME`, second is `DEPLOY_TYPE`. If the script exits non-zero, report the error and stop.

**If `DEPLOY_TYPE = http` and `DEPLOY_APP_NAME` is non-empty:**

The app will be served at `http://localhost/{DEPLOY_APP_NAME}/` via Traefik path-prefix routing. The SPA base path must be set in the worktree **before building** so assets are referenced correctly.

Run the SPA base-path correction script on the **worktree**:

```bash
bash .specify/extensions/echelon/scripts/bash/fix-spa-base.sh "{worktree_path}" "{DEPLOY_APP_NAME}"
```

If the script patches any files, those changes are correct and expected. **Immediately stage them** in the worktree so subsequent git operations (internal to codegen or merge strategies) cannot overwrite them:

```bash
cd "{worktree_path}" && git add -A && git commit -m "chore: apply SPA base path for {DEPLOY_APP_NAME} [skip ci]" --allow-empty
```

This makes the fix durable — it is now in the worktree's git history and cannot be lost by a `git checkout -- .` or `git reset`.

**If `DEPLOY_TYPE = cli` or no deploy-state.json exists:** skip this step. No subpath correction needed.

---

## Step 4c: Inject Build Constraints (Lessons)

Read the lessons file for this spec — it records invariants learned from previous failed runs:

```bash
cat "specs/{spec_id}-{spec_name}/lessons.md" 2>/dev/null || echo "(no lessons yet)"
```

Also read the project-wide pitfalls:

```bash
cat ".specify/knowledge-base/pitfalls.yaml" 2>/dev/null || echo "(no pitfalls yet)"
```

**If either file has content:** these are HARD constraints for the build step. Every lesson is an invariant that MUST NOT be violated by any implementation. Pass them verbatim to the strategy:

- For `strategy = default`: include in the speckit-echelon-implementer (IMPLEMENTER) dispatch prompt under a `## Mandatory Constraints (Lessons)` header
- For `strategy = codegen`: write the lessons as additional SOAR prohibit preferences before the pipeline starts (see codegen Phase A.7)

Do not skip this step even if lessons seem obvious. Lessons exist because these invariants were violated at least once.

---

## Step 5: Build (on host)

Read from the **worktree path** (synced in Step 4 — this is the single source of truth):

- `specs/{spec_id}-*/spec.md` — the feature requirements
- `specs/{spec_id}-*/tasks.md` — the implementation tasks (may include `## Bugfix N:` sections appended by `echelon.bugfix`)
- `specs/{spec_id}-*/bugfix-*.md` — if any exist, read the latest one. This is the diagnosis report from `echelon.bugfix`: root cause, fix scope, test strategy. Pass it to the build step as additional context so the implementer knows exactly what to fix and what test to write.

**Dispatch on `strategy`:**

**`strategy = default`** — follow the `echelon.build` instructions directly (you are the LLM, reasoning on the host). Always write implementation files to the **worktree path** — never to CWD.

**`strategy = codegen`** — invoke the `speckit-echelon-codegen` skill with argument `{spec_id}-{spec_name}`. The codegen pipeline manages its own quality gates (SOAR CQ-ISC, Ψ ≥ 0.70, Tier 1 tests). Always write implementation files to the **worktree path** — never to CWD. On impasse (`codegen-impasse.md` written), stop and report the impasse to the human instead of entering the feedback loop.

**ABSOLUTE RULE — codegen skill failures are HARD STOPS. No fallback, no substitution:**

If the `speckit-echelon-codegen` skill invocation fails for any reason — `disable-model-invocation`, skill not found, error returned, timeout — stop immediately and report:

```text
✗ strategy=codegen failed: {exact error from skill tool}

  The codegen skill cannot be invoked in this context.
  Options:
    1. Re-run with strategy=default to use the standard build pipeline
    2. Fix the codegen skill configuration and retry
```

Always stop and report codegen invocation failure before Step 6. Do NOT fall back to `strategy=default`, implement directly, or continue to Step 6.

On subsequent outer iterations (`outer_iter > 0`) after a failed Docker verify, **both strategies** fix failures by analysing the Docker verify output and editing the relevant files directly in the worktree — there is no need to re-run the full build pipeline to fix targeted test failures.

**If any step fails with a git error:** always report the exact error and stop. Do not attempt alternative git commands (cherry-pick, rebase, merge) to work around it.

Track the outer iteration count (`outer_iter`, starting at 0). After each build, proceed to Step 6.

---

## Step 6: Verify (in Docker)

Determine the Docker image to use:
- Read `detected_image` from `.specify/extensions/echelon/echelon-config.yml`
- Fallback: `ubuntu:24.04`

```bash
docker run --rm \
  -v "{worktree_path}:/workspace:ro" \
  {docker_image} \
  sh /workspace/verify.sh
```

Capture exit code and output.

> **Note:** `verify.sh` is a shell script that the build step should create in the worktree (at `{worktree_path}/verify.sh`). It MUST include: (1) the test suite run, and (2) a smoke test that starts the built application and verifies it serves an HTTP response. A blank page passes unit tests. The smoke test is what catches it. The worktree is mounted read-only; `verify.sh` must copy files to `/tmp` before installing dependencies.
>
> **SPA asset-path check (MANDATORY for Vite/CRA/Next.js builds):** After building but before starting the app, parse the built `index.html` and verify that `<script src=...>` and `<link href=...>` asset paths begin with the expected base prefix. If `DEPLOY_APP_NAME` is set, the prefix must be `/{DEPLOY_APP_NAME}/assets/`. If no subpath deployment, the prefix must be `/assets/`. A blank page with no console errors is indistinguishable from a correctly working page when assets are missing — the asset-path check catches it at build time, not at runtime.
>
> **Example check in verify.sh:**
>
> ```sh
> # Verify built assets reference the correct subpath
> BASE_PREFIX="${DEPLOY_APP_NAME:+/${DEPLOY_APP_NAME}}/assets/"
> if grep -q 'src=' /tmp/app/dist/index.html; then
>   if ! grep -qE "src=['\"]${BASE_PREFIX}" /tmp/app/dist/index.html; then
>     echo "✗ Built index.html assets do not reference expected prefix '${BASE_PREFIX}'" >&2
>     echo "  Check that vite.config.js has: base: '/${DEPLOY_APP_NAME}/'" >&2
>     grep -oE "src=['\"][^'\"]*['\"]" /tmp/app/dist/index.html | head -3 >&2
>     exit 1
>   fi
>   echo "✓ Asset paths verified (prefix: ${BASE_PREFIX})"
> fi
> ```

Parse the Docker exit code:
- Exit code `0` → Docker verification passed → proceed to Step 6b (coverage-map check)
- Exit code non-zero → verification failed → proceed to Step 7 (feedback)

---

## Step 6b: Coverage-Map Check (on host)

After Docker verification passes, check whether any requirements lack automated coverage.

Look for `specs/{spec_id}-*/coverage-map.md` in the current working directory.

**If coverage-map.md does not exist:**
- Warn: **"No coverage-map.md found for spec {spec_id}. Proceeding without coverage check."**
- Set `verified = full` (Docker tests passed — absence of coverage-map is not a blocker)
- Proceed to Step 8.

**If coverage-map.md exists**, read it and classify each row:

- **`coverage_type = automated`**: fully verified — no action needed.
- **`coverage_type = manual`**: intentionally manual — auto-accepted. speckit-echelon-sentinel (SENTINEL) marked these "manual only" by design (Canvas rendering, frame rates, visual checks). Always allow them to pass; they do not block the run.
- **`coverage_type = none` or empty**: genuinely missing automation — these are gaps.

Decision logic:
- If **zero `none`/empty rows**: `verified = full` → proceed to Step 8.
- If **any `none`/empty rows**: these are real gaps. Assess whether they can be automated (i.e., are they logic/API tests, not Canvas/visual/performance browser tests?).
  - If all `none`/empty rows are for Canvas rendering, frame rates, visual output, or browser-only behaviour: auto-accept them as manual-by-nature, set `verified = full`, proceed to Step 8.
  - If any `none`/empty rows are for logic, API, or state that *can* be unit/integration tested: set `verified = partial`, and proceed to Step 7 (feedback loop) to add the missing tests.

> Logic gaps always trigger feedback (Step 7). Manual coverage and browser-only gaps are auto-accepted; they do NOT trigger feedback. Always keep manual-by-design gaps internal; do not surface them to the human.

---

## Step 7: Feedback (on host)

If `outer_iter >= max_outer`, report **"Max iterations ({max_outer}) reached without convergence."** and proceed to Step 8 with whatever is in the worktree.

Read the verification failure output from Step 6. Follow `echelon.feedback` instructions on the host: analyze failures, fix implementation files in the worktree. Increment `outer_iter` and return to Step 5.

---

## Step 7b: Write Lessons

If `outer_iter > 0` (at least one feedback cycle was needed) or Docker verification failed at any point, extract the invariants learned and append them to `specs/{spec_id}-{spec_name}/lessons.md` in CWD:

```bash
LESSONS_FILE="specs/{spec_id}-{spec_name}/lessons.md"
touch "${LESSONS_FILE}"
```

For each distinct failure encountered during this run, append an entry:

```markdown
## Lesson {n} — {date}

**Trigger**: {what went wrong — one sentence}
**Root cause**: {why — specific file/line/mechanism}
**Invariant**: {the rule that must hold from now on — imperative sentence starting with ALWAYS or NEVER}
**Applies to**: {default | codegen | both}
```

Example from the SPA base path bug:

```markdown
## Lesson 1 — 2026-04-16

**Trigger**: Deployed app was blank page — JS assets missing subpath prefix
**Root cause**: vite.config.js `base:` was overwritten by git merge from feature branch that predated the base setting
**Invariant**: ALWAYS run fix-spa-base.sh AND commit the result before any build step when deploy type is http. NEVER allow git operations to overwrite the staged base path fix.
**Applies to**: both
```

Copy the updated `lessons.md` into the worktree so it is committed with the build:

```bash
cp "${LESSONS_FILE}" "{worktree_path}/specs/{spec_id}-{spec_name}/lessons.md"
```

If `outer_iter = 0` and verification passed on the first attempt: skip this step.

---

## Step 8: Commit and Push to Feature Branch

Push all implementation to the feature branch (or harness branch in legacy mode).

Resolve `{push_branch}`:
- Feature branch mode: `{push_branch}` = `{feature_branch}`
- Legacy mode (no feature branch): `{push_branch}` = `harness/{spec_id}/{strategy}/iter-{outer_iter}`

```bash
PYTHONPATH=.specify/extensions/echelon python -m harness gitops commit-push \
  '{worktree_path}' '{push_branch}' 'harness: {spec_id} build iter-{outer_iter} [skip ci]'
```

---

## Step 9: Merge to Main

After verification passes, merge the feature branch to main.

**Option A — PR tool available (gh/glab):**

```bash
PYTHONPATH=.specify/extensions/echelon python -m harness gitops open-pr \
  '{push_branch}' '{spec_id}' '{strategy}' '{spec_name}'

PYTHONPATH=.specify/extensions/echelon python -m harness gitops merge-pr '{pr_url}'
```

`open-pr` prints `pr_url: <url>` — capture it for the `merge-pr` call and for Step 10.

**Option B — no PR tool (local repo):**

If no PR tool is available, merge directly:

```bash
PYTHONPATH=.specify/extensions/echelon python -m harness gitops local-merge \
  '{push_branch}' '{spec_id}' '{spec_name}'
```

If merge fails (branch protection, conflicts), always report the error and stop — do not retry or ask the user for a workaround.

`auto_merge=false` skips this step entirely and leaves the branch open for manual review.

---

## Step 9b: Deploy

Runs only when `auto_merge=true` and the merge in Step 9 succeeded.

Check whether deploy is enabled:

```bash
ECHELON_EXT="$(git rev-parse --show-toplevel)/.specify/extensions/echelon"
_deploy_enabled=$(bash "${ECHELON_EXT}/scripts/bash/echelon-config-get.sh" deploy.enabled 2>/dev/null || echo "true")
```

If `_deploy_enabled = false`: print `deploy: skipped (deploy.enabled = false)` and proceed directly to Step 10.

Otherwise, invoke the `speckit-echelon-deploy` skill now. This will:

1. Check the CI/CD fingerprint — if the project changed, auto-regenerate CI/CD artifacts via `speckit-echelon-cicd` first
2. Run the blue/green (HTTP) or tag-pointer (CLI) deploy

If `speckit.echelon.deploy` exits with an error, always report it clearly and continue; **do not fail the harness run** — the build and merge succeeded. The user can re-run `speckit.echelon.deploy` manually to retry the deploy.

If `auto_merge=false`: skip this step entirely. The PR is open for review; deploy will happen when the user is ready.

---

## Step 10: Display Result

Print a single formatted block:

```
════════════════════════════════════════════════
  ✓ {spec_id} — {spec_name}
════════════════════════════════════════════════
  Status:     DONE — merged to {default_branch}
  Strategy:   {strategy}
  Branch:     {feature_branch}  →  {default_branch}
  Iterations: {outer_iter + 1}
  Tests:      {passing_count} passing

  Coverage
    Automated:  {n} requirements
    Manual:     {n} requirements  (browser-only — accepted)
    Deferred:   {n} requirements  (future milestones)

  What's next
    Run a new feature:  speckit.echelon.run <description>
    Then build it:      speckit.echelon.harness-run <spec_id>
════════════════════════════════════════════════
```

If merge was skipped (`auto_merge=false`) or failed, replace the Status line:
```
  Status:     VERIFIED — branch {feature_branch} ready to merge
  PR:         {pr_url}
```

If `verified = PARTIAL` (logic gaps triggered a feedback loop), replace Status:
```
  Status:     PARTIAL — {n} logic gap(s) remain after {max_outer} iterations
              See PR for details: {pr_url}
```

If `verified = NO` (max iterations, Docker did not pass), replace Status:
```
  Status:     DID NOT CONVERGE — {max_outer} iterations exhausted
              Last build state is on branch {feature_branch}
```

> Always auto-accept manual-by-design gaps and trigger another build iteration for logic gaps. Never ask the human to choose between options or approve deferrals.
