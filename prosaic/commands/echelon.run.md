---
name: speckit.echelon.run
description: Full autonomous cognitive squad run — requires speckit.echelon.init first
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

Always stop on any failure — do not proceed to launch.

```bash
# echelon CLI on PATH
if ! command -v echelon >/dev/null 2>&1; then
  echo "✗ echelon not on PATH. Run: bash ~/.echelon/install.sh" >&2
  exit 1
fi

# echelon CLI version — must be >= 2.2.0 (Python harness, ECHELON_SQUAD_ACTIVE guard)
# Older builds have no --version flag and route 'echelon spec run' through the skill path,
# causing infinite recursion (echelon.run.md → echelon spec run → echelon.run.md → ...).
ECHELON_VER=$(echelon --version 2>/dev/null | awk '{print $2}')
if [ -z "$ECHELON_VER" ]; then
  echo "✗ echelon CLI is outdated (pre-2.2.0 — no --version support)." >&2
  echo "  An old build will recurse infinitely when 'echelon spec run' is invoked." >&2
  echo "  Run: bash ~/.echelon/install.sh" >&2
  exit 1
fi
echo "✓ echelon CLI: $(command -v echelon) (${ECHELON_VER})"

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
  echo "  Run: echelon workspace init" >&2
  exit 1
fi
echo "✓ Config: ${ECHELON_CONFIG}"
```

---

## Step 3: Launch

Run this command **synchronously in the foreground** using the Bash tool — do NOT use `run_in_background`. The harness streams phase progress and agent output directly to the terminal; running in background silences all of that and sends output to a temp file instead.

```bash
cd "${PROJECT_ROOT}" && echelon spec run "$@"
```

This command delegates entirely to the Python squad harness (`src/harness/squad.py`).
Phase routing is deterministic — COMMANDER is dispatched only for judgment calls
(escalation, contradictions, human gates in guided mode).

Monitor: `runs/<run-id>/state.json` · `runs/<run-id>/reasoning-journal.jsonl`
Run `cat runs/.current` to get the active run ID.

Each `runs/<run-id>/` directory is durable local run history. Its `staging/`
subdirectory is the pre-WHAT discovery area and control-plane inbox; after WHAT,
canonical product artifacts live under `runs/<run-id>/specs/<spec-id>/` until
they are published to the project-level `specs/<spec-id>/` directory.
