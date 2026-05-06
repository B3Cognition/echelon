# Phase: bugfix-1-init
# Source: echelon.bugfix.md §Steps 0–1 — Init
# Read by: COMMANDER before starting bugfix workflow

---

## Step 0: Ensure on Default Branch

Before reading any spec files, verify the project working directory is on the
default branch (`main` or `master`). `echelon.bugfix` writes artifacts to the
feature branch — it must start from a known base so the checkout is predictable.

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
  echo "Warning: working directory is on '$CURRENT', expected '$DEFAULT_BRANCH'. Switching."
  # Stash any uncommitted changes so they are not lost
  if [ -n "$(git status --porcelain)" ]; then
    STASH_MSG="echelon-bugfix-auto-stash-$(date +%Y%m%d-%H%M%S)"
    git stash push -u -m "$STASH_MSG"
    echo "Uncommitted changes stashed as: $STASH_MSG (recover with: git stash pop)"
  fi
  git checkout "$DEFAULT_BRANCH"
fi
```

Proceed only once the working directory is confirmed on the default branch.

---

## Step 1: Parse Input

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| `spec_id` | — | Required if multiple specs exist (e.g. `001`). |
| `description` | — | Required. What is broken or what needs to change. |

If `description` is missing: ask **"What needs to be fixed or changed?"** and stop.

If `spec_id` is absent and multiple specs exist under `specs/`, list them and ask which one. If only one spec exists, use it automatically.

Locate `specs/{spec_id}-*/`. Extract `{spec_name}`. If not found: report **"Spec `{spec_id}` not found."** and stop.

Read the following — pass to every agent dispatch:

- `specs/{spec_id}-{spec_name}/spec.md`
- `specs/{spec_id}-{spec_name}/coverage-map.md` (if exists)
- `specs/{spec_id}-{spec_name}/tasks.md` (if exists)
- `.specify/squad/deploy-state.json` (if exists)
- The relevant source files based on `description` (the component, hook, API call, config file, or test most likely related to the issue)
