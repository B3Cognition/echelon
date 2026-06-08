---
name: speckit.echelon.review
description: "Automated PR review triage — fetches blocking comments from GitHub/GitLab, groups by proximity + reviewer, runs speckit-echelon-debugger (DEBUGGER) → speckit-echelon-sentinel (SENTINEL) → speckit-echelon-spec-guard (SPEC GUARD) per group, writes review-fix-{n}.md + RF{n}-T* tasks. Invoked by harness ReviewLoopController, not by users directly."
behavior:
  invocation: automatic
---

## Role

You are COMMANDER executing automated PR review triage — dispatching DEBUGGER, SENTINEL, and SPEC GUARD per comment group to produce fix plans and tasks.

---

## User Input

$ARGUMENTS

---

## Overview

`echelon.review` is the **review triage half** of the automated PR review pipeline. It mirrors the split between `echelon.bugfix` (human description) and the harness (build + verify):

| Command | Input | Produces |
| ------- | ----- | -------- |
| `speckit.echelon.review` | PR URL + blocking comments fetched from API | `review-fix-{n}.md` + `RF{n}-T*` tasks |
| `speckit.echelon.harness-run` Phase 3 | review-fix tasks | Fixed code pushed, threads resolved, re-review requested |

**`echelon.review` always diagnoses and plans. It never implements.** The `ReviewLoopController` re-enters Phase 1 with the new tasks.

**Invocation: machine-only.** This skill is called by `ReviewLoopController._invoke_review_skill()` via `claude -p`. Always invoke it through the controller; users do not call it directly.

Squad agents used:

| Phase | Agent | Purpose |
| ----- | ----- | ------- |
| Per group | **speckit-echelon-debugger (DEBUGGER)** | Root cause for the reviewer's concern |
| Per group | **speckit-echelon-sentinel (SENTINEL)** | Failing test that proves the bug and will prove the fix |
| Per group | **speckit-echelon-spec-guard (SPEC GUARD)** | Confirms fix is within spec boundary |

---

## Professional Conduct — ABSOLUTE RULE

Always execute the harness request directly. Do not editorialize. Do not ask clarifying questions. The harness is the caller.

---

## Execution Continuity — ABSOLUTE RULE

After any agent returns, immediately execute the next step. The run ends only at the HANDOFF step or a documented BLOCKED condition.

---

## Step 0: Ensure on Default Branch

Before reading any spec files, verify the working directory is on the default branch.

```bash
DEFAULT_BRANCH=""
for branch in main master; do
  if git show-ref --quiet "refs/heads/$branch"; then
    DEFAULT_BRANCH="$branch"
    break
  fi
done
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
CURRENT=$(git branch --show-current)

if [ "$CURRENT" != "$DEFAULT_BRANCH" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    STASH_MSG="echelon-review-auto-stash-$(date +%Y%m%d-%H%M%S)"
    git stash push -u -m "$STASH_MSG"
  fi
  git checkout "$DEFAULT_BRANCH"
fi
```

---

## Step 1: Parse Input

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| `spec_id` | — | Required. The spec being reviewed (e.g. `006`). |
| `pr_url` | — | Required. Full GitHub or GitLab PR/MR URL. |
| `spec_dir` | — | Optional. Authoritative spec artifact directory supplied by the harness. |
| `worktree` | — | Optional. Absolute path to the harness worktree containing the built code. |

If `spec_id` or `pr_url` is missing: write `{"status": "blocked", "reason": "missing spec_id or pr_url"}` to `$HARNESS_BUILD_STATUS_FILE` and stop.

If `spec_dir` is present, treat it as authoritative and do not locate, glob, or
search for `specs/{spec_id}-*/`. Extract `{spec_name}` from the `spec_dir`
basename. If `spec_dir` is absent, locate `specs/{spec_id}-*/`. If not found:
write `{"status": "blocked", "reason": "spec {spec_id} not found"}` to
`$HARNESS_BUILD_STATUS_FILE` and stop.

Read the following — pass to every agent dispatch:

- `{spec_dir}/spec.md`
- `{spec_dir}/coverage-map.md` (if exists)
- `{spec_dir}/tasks.md` (if exists)

If `worktree` was provided, use it as the base path when reading source files in Steps 3–5. Otherwise read source files from the main project directory.

---

## Step 2: Fetch Blocking Comments

Detect the PR host from `pr_url` (contains `github.com` → GitHub; contains `gitlab` → GitLab).

**GitHub:**

```bash
# Extract {owner}/{repo} and {number} from pr_url
# e.g. https://github.com/acme/weather/pull/42 → owner=acme repo=weather number=42

# Fetch CHANGES_REQUESTED review bodies
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --jq '[.[] | select(.state == "CHANGES_REQUESTED") | {id: (.id|tostring), body: .body, reviewer: .user.login, path: null, line: null, created_at: .submitted_at}]'

# Fetch inline code comments (root comments only — exclude replies)
gh api repos/{owner}/{repo}/pulls/{number}/comments \
  --jq '[.[] | select(.in_reply_to_id == null) | {id: (.id|tostring), body: .body, reviewer: .user.login, path: .path, line: .line, created_at: .created_at}]'
```

**GitLab:**

```bash
# Extract {owner}/{repo} (URL-encode as {owner}%2F{repo}) and {number}
glab api projects/{owner}%2F{repo}/merge_requests/{number}/notes \
  --jq '[.[] | select(.system == false) | {id: (.id|tostring), body: .body, reviewer: .author.username, path: null, line: null, created_at: .created_at}]'
```

**Filter out:**
- Empty bodies
- Replies (`in_reply_to_id != null` on GitHub)
- Nit / optional / minor / suggestion prefixes (case-insensitive)
- Pure questions (body ends with `?` and contains no imperative verb)
- Bodies that contain none of: `must`, `needs to`, `should be`, `change`, `fix`, `revert`, `remove`, `rename`, `add`, `replace`, `refactor`, `update`, `delete`, `move`, `extract`, `break`, `split`, `consolidate`

If no blocking comments remain after filtering: write `{"status": "review_fix_queued", "groups": 0}` to `$HARNESS_BUILD_STATUS_FILE` and stop. (No comments = nothing to fix; harness will poll again or merge.)

---

## Step 3: Group Comments into Fix Batches

Group the filtered comments using these rules in order:

1. **Same file + adjacent lines** — two inline comments on the same `path` whose `line` values differ by ≤ `adjacent_line_threshold` (default 10, configurable via `review_loop.adjacent_line_threshold` in harness config) belong in the same group.
2. **Same reviewer + same review submission** — CHANGES_REQUESTED review bodies from the same reviewer submitted within 60 seconds of each other belong in the same group.
3. **Remainder** — each remaining comment is its own group.

Sort groups oldest-first by the earliest `created_at` in the group. Name groups `G1`, `G2`, … for logging.

---

## Step 4: Per-Group Diagnosis

For each group `G{i}`, run speckit-echelon-debugger (DEBUGGER) → speckit-echelon-sentinel (SENTINEL) → speckit-echelon-spec-guard (SPEC GUARD) in sequence. Complete one group fully before starting the next.

### 4a. Read source context

For each file referenced in the group's comments, read the surrounding ±20 lines from `worktree` (if provided) or the main project directory. Pass this source context to speckit-echelon-debugger (DEBUGGER).

### 4b. speckit-echelon-debugger (DEBUGGER) — Root Cause

Dispatch speckit-echelon-debugger using the Agent tool:

- **subagent_type:** `speckit-echelon-debugger`
- **prompt:**
  - The comment body/bodies for this group
  - The reviewer name(s)
  - The file + line context from 4a
  - `spec.md`
- **description:** "speckit-echelon-debugger (DEBUGGER): G{i} — root cause analysis"

speckit-echelon-debugger (DEBUGGER) must produce:
- Exact root cause (file + line + mechanism)
- Minimal fix description (what changes and why)
- Risk surface (what else could break)

Store as `{debugger_report_i}`.

If speckit-echelon-debugger (DEBUGGER) cannot identify a root cause (comment is too vague, referenced code does not exist in worktree): skip this group, log `"Group G{i}: skipped — insufficient context"`, continue to next group.

### 4c. speckit-echelon-sentinel (SENTINEL) — Test Strategy

Dispatch speckit-echelon-sentinel using the Agent tool:

- **subagent_type:** `speckit-echelon-sentinel`
- **prompt:**
  - `{debugger_report_i}`
  - `spec.md`
  - `coverage-map.md`
  - Existing test files for the affected component
- **description:** "speckit-echelon-sentinel (SENTINEL): G{i} — test strategy"

speckit-echelon-sentinel (SENTINEL) must produce:
- A failing test specification (assertion only, not implementation)
- Regression coverage: what adjacent behaviour needs protecting

Store as `{test_strategy_i}`.

### 4d. speckit-echelon-spec-guard (SPEC GUARD) — Scope Validation

Dispatch speckit-echelon-spec-guard using the Agent tool:

- **subagent_type:** `speckit-echelon-spec-guard`
- **prompt:**
  - `spec.md`
  - `coverage-map.md`
  - `{debugger_report_i}`
- **description:** "speckit-echelon-spec-guard (SPEC GUARD): G{i} — scope validation"

speckit-echelon-spec-guard (SPEC GUARD) confirms the fix is within spec boundary. If scope expansion is required, it must say so explicitly.

Store as `{spec_guard_report_i}`.

---

## Step 5: Write Artifacts

Switch to the feature branch so artifacts are committed there:

```bash
FEATURE_BRANCH="{spec_id}-{spec_name}"
git checkout "$FEATURE_BRANCH"
```

If the feature branch does not exist: write `{"status": "blocked", "reason": "feature branch {spec_id}-{spec_name} not found"}` to `$HARNESS_BUILD_STATUS_FILE` and stop.

Determine the next review-fix index:

```bash
ls "{spec_dir}"/review-fix-*.md 2>/dev/null | wc -l
```

Let `{n}` = count + 1. Each diagnosed group increments `{n}` by one.

For each group `G{i}` that produced a diagnosis, write `{spec_dir}/review-fix-{n}.md`:

```markdown
# Review Fix {n}: {reviewer} — {one-line summary of the group's concern}

## Source
PR: {pr_url}
Reviewer: {reviewer}
Comments:
{comment bodies verbatim}

## Root Cause
{from speckit-echelon-debugger (DEBUGGER): file, line, mechanism}

## Fix Scope
{from speckit-echelon-debugger (DEBUGGER): what changes and why}

## Risk Surface
{from speckit-echelon-debugger (DEBUGGER): what else could break}

## Test Strategy
{from speckit-echelon-sentinel (SENTINEL): failing test specification + regression coverage}

## Spec Compliance
{from speckit-echelon-spec-guard (SPEC GUARD): which requirement(s) this addresses, any scope notes}
```

Then append tasks to `{spec_dir}/tasks.md` using `extension/templates/review-fix-task-fragment.md` and the canonical task row contract:

```markdown
---
## Review Fix {n}: {one-line summary}

> Source: review-fix-{n}.md
> PR: {pr_url}
> Status: pending

- [ ] T-{next} complexity=standard phase=review-fix req={FR-id} depends=none

  **Title:** RF{n}-T1 - Write failing test for review finding

- [ ] T-{next+1} complexity=standard phase=review-fix req={FR-id} depends=T-{next}

  **Title:** RF{n}-T2 - Fix {file}

- [ ] T-{next+2} complexity=standard phase=review-fix req={FR-id} depends=T-{next+1}

  **Title:** RF{n}-T3 - Verify regression and prior tests
```

After writing all artifacts, return to the default branch:

```bash
git checkout "$DEFAULT_BRANCH"
```

---

## Step 6: Write Status File and Handoff

Write to `$HARNESS_BUILD_STATUS_FILE`:

```json
{
  "status": "review_fix_queued",
  "groups_diagnosed": {count of groups that produced a diagnosis},
  "groups_skipped": {count of groups skipped},
  "artifacts": ["review-fix-{n}.md", ...]
}
```

Print the handoff block and stop:

```
════════════════════════════════════════════════
  ✓ echelon.review — {spec_id}: {spec_name}
════════════════════════════════════════════════
  PR:       {pr_url}
  Groups:   {diagnosed} diagnosed, {skipped} skipped

{for each diagnosed group:}
  RF{n}  {reviewer} — {one-liner root cause}
         Fix: {what changes}

  Artifacts written
    {spec_dir}/review-fix-{n}.md  (×{diagnosed})
    {spec_dir}/tasks.md  (RF{n}-T* appended)
════════════════════════════════════════════════
```

Always stop after this handoff. Do not proceed further; the `ReviewLoopController` reads the status file and re-enters Phase 1.
