---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — drives pre-code phases via deterministic harness"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Step 1: Anchor project root

```bash
PROJECT_ROOT=$(pwd)
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
ECHELON_CONFIG="${ECHELON_EXT}/echelon-config.yml"
echo "PROJECT_ROOT=${PROJECT_ROOT}"
echo "ECHELON_EXT=${ECHELON_EXT}"
echo "ECHELON_CONFIG=${ECHELON_CONFIG}"
```

---

## Step 2: Preflight checks

Any failure is a HARD STOP — do not proceed to launch.

```bash
# echelon CLI on PATH
if ! command -v echelon >/dev/null 2>&1; then
  echo "✗ echelon not on PATH. Run: bash ~/.echelon/install.sh" >&2
  exit 1
fi
echo "✓ echelon CLI: $(command -v echelon)"

# Extension installed
if [ ! -d "${ECHELON_EXT}" ]; then
  echo "✗ Echelon extension not installed: ${ECHELON_EXT}" >&2
  echo "  Run: specify extension add echelon" >&2
  exit 1
fi
echo "✓ Extension: ${ECHELON_EXT}"

# Project initialized
if [ ! -f "${ECHELON_CONFIG}" ]; then
  echo "✗ Project not initialized — config not found: ${ECHELON_CONFIG}" >&2
  echo "  Run: echelon init" >&2
  exit 1
fi
echo "✓ Config: ${ECHELON_CONFIG}"
```

---

## Step 3: Launch

```bash
cd "${PROJECT_ROOT}" && echelon run "$@"
```

This command delegates entirely to the Python squad harness (`src/harness/squad.py`).
Phase routing is deterministic — COMMANDER is dispatched only for judgment calls
(escalation, contradictions, human gates in guided mode).

Monitor: `.specify/squad/state.json` · `.specify/squad/reasoning-journal.jsonl`
