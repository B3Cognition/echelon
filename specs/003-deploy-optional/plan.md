# Optional Deploy — Implementation Plan

## Overview

Three targeted file changes. No new scripts. No new abstractions. The existing `echelon-config-get.sh` resolver is the only config-reading mechanism used.

**Entry point for all consumers:** `echelon-config-get.sh deploy.enabled`
- Returns `true` or `false` (string)
- Returns exit 1 (key not found) when key is absent — callers treat this as `true`
- Uses `specify extension config resolve echelon` when available, falls back to direct YAML read

---

## Tasks

### T-001 — Add `deploy.enabled` to `config-template.yml`

**File:** `extension/config-template.yml`

**Change:** Add `enabled: true` as the first key in the `deploy:` section, above `type:`.

```yaml
deploy:
  # Set to false to skip all deploy infrastructure checks and post-merge deploy.
  # Use when the project does not need echelon's local blue/green CD.
  # Default: true
  enabled: true

  # Deployment type. Controls which infrastructure is used.
  # [values: http | cli]  Default: http
  type: http
  ...
```

**Acceptance:** `echelon-config-get.sh deploy.enabled` returns `true` on a freshly initialised project.

**Dependencies:** None.

---

### T-002 — Early-exit in `validate-deploy.sh` when deploy disabled

**File:** `extension/scripts/bash/validate-deploy.sh`

**Change:** Insert a deploy-enabled check at the top of the script, immediately after the initial `echo` line and before check §1 (deploy-state.json existence). Use `echelon-config-get.sh` via the same `SCRIPTS_DIR`-relative path pattern already used in other scripts.

```bash
# ── Deploy enabled check ──────────────────────────────────────────────────────
_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_DEPLOY_ENABLED="true"
if _val="$(bash "${_SCRIPTS_DIR}/echelon-config-get.sh" deploy.enabled 2>/dev/null)"; then
  _DEPLOY_ENABLED="${_val}"
fi

if [ "${_DEPLOY_ENABLED}" = "false" ]; then
  echo "deploy: validation skipped (deploy.enabled = false)"
  exit 0
fi
```

**Placement:** After `set -euo pipefail` and variable declarations, before the first `echo "deploy: validating..."` line and all infrastructure checks.

**Fail-safe:** If `echelon-config-get.sh` exits non-zero (key absent, no `.specify/` root, `specify` not available), `_DEPLOY_ENABLED` stays `true` and all existing checks run unchanged.

**Acceptance:**
- `deploy.enabled: false` → script prints one line and exits 0, Traefik/Docker never checked
- `deploy.enabled: true` or key absent → existing behaviour, no regression
- `specify` unavailable + `deploy.enabled: false` in raw YAML → exits 0 (fallback in echelon-config-get.sh reads YAML directly)

**Dependencies:** T-001 (so the key exists in template; the script itself works even without it due to fail-safe).

---

### T-003 — Skip Step 9b in `echelon.harness-run.md` when deploy disabled

**File:** `extension/commands/echelon.harness-run.md`

**Change:** Prepend a deploy-enabled guard to §Step 9b. The check uses `echelon-config-get.sh` via the same `ECHELON_EXT` path already established earlier in the command.

Replace the current Step 9b opening:

```
## Step 9b: Deploy

Runs only when `auto_merge=true` and the merge in Step 9 succeeded.
```

With:

```
## Step 9b: Deploy

Skip this step entirely if `auto_merge=false` or the merge in Step 9 did not succeed.

Also skip if deploy is disabled:

```bash
ECHELON_EXT="$(git rev-parse --show-toplevel)/.specify/extensions/echelon"
_deploy_enabled=$(bash "${ECHELON_EXT}/scripts/bash/echelon-config-get.sh" deploy.enabled 2>/dev/null || echo "true")
```

If `_deploy_enabled = false`: print `deploy: skipped (deploy.enabled = false)` and proceed directly to Step 10.

Otherwise (enabled or key absent), invoke the `speckit-echelon-deploy` skill as today.
```

**Acceptance:**
- `deploy.enabled: false` + `auto_merge=true` + merge succeeded → Step 9b prints one line and skips to Step 10
- `deploy.enabled: true` + `auto_merge=true` + merge succeeded → skill invoked, existing behaviour
- `deploy.enabled: false` + `auto_merge=false` → Step 9b already skipped by the existing `auto_merge` guard; the new check is never reached

**Dependencies:** T-001, T-002.

---

## Change Summary

| File | Lines changed (est.) | Risk |
|------|---------------------|------|
| `extension/config-template.yml` | +4 | None — additive only |
| `extension/scripts/bash/validate-deploy.sh` | +8 | Low — fail-safe default preserves all existing behaviour |
| `extension/commands/echelon.harness-run.md` | +7 | Low — guard is additive, existing path unchanged |

**Total: ~19 lines across 3 files.**
