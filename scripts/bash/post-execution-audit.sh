#!/usr/bin/env bash
# post-execution-audit.sh — Post-execution output constraint checks
# Usage: ./scripts/bash/post-execution-audit.sh --agent AGENT_NAME --output-dir OUTPUT_DIR
# Exit 0 = PASS, Exit 1 = FAIL (issues on stdout)
#
# Checks per agent:
#   IMPLEMENTER — test files exist in output dir
#   GATEKEEPER  — if verdict is KILL, evidence section exists
#   DEBUGGER    — root cause section exists before fix section
#   Default     — PASS (no agent-specific constraints)

set -uo pipefail

# ── Argument parsing ──────────────────────────────────────────────

AGENT=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)      AGENT="$2";      shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 0 ;;  # fail-open
  esac
done

if [ -z "$AGENT" ]; then
  echo "WARN: --agent is required. Passing audit (fail-open)." >&2
  exit 0
fi

if [ -z "$OUTPUT_DIR" ]; then
  echo "WARN: --output-dir is required. Passing audit (fail-open)." >&2
  exit 0
fi

ISSUES=()

# ── Helper: search files for a section heading ────────────────────

has_section() {
  local dir="$1" pattern="$2"
  grep -rli "$pattern" "$dir" 2>/dev/null | head -1
}

# ── IMPLEMENTER: test files must exist ────────────────────────────

audit_implementer() {
  local test_files
  test_files=$(find "$OUTPUT_DIR" -type f \( \
    -name "*.test.*" -o -name "*.spec.*" -o -name "*_test.*" -o -name "test_*" \
  \) 2>/dev/null | head -1)

  if [ -z "$test_files" ]; then
    ISSUES+=("IMPLEMENTER: No test files found in $OUTPUT_DIR (violates 'NEVER skip tests')")
  fi
}

# ── GATEKEEPER: KILL verdict requires evidence ────────────────────

audit_gatekeeper() {
  # Look for feasibility or kill report files
  local kill_file
  kill_file=$(find "$OUTPUT_DIR" -type f \( \
    -name "feasibility.md" -o -name "kill-report.md" \
  \) 2>/dev/null | head -1)

  if [ -z "$kill_file" ]; then
    # No feasibility file found — nothing to audit
    return 0
  fi

  # Check if verdict is KILL
  if grep -qi "verdict.*kill\|KILL" "$kill_file" 2>/dev/null; then
    # Evidence section must exist
    if ! grep -qi "evidence\|citation\|justification" "$kill_file" 2>/dev/null; then
      ISSUES+=("GATEKEEPER: KILL verdict without evidence section in $kill_file (violates 'NEVER kill without citing specific evidence')")
    fi
  fi
}

# ── DEBUGGER: root cause before fix ───────────────────────────────

audit_debugger() {
  local debug_file
  debug_file=$(find "$OUTPUT_DIR" -type f -name "debug-report.md" 2>/dev/null | head -1)

  if [ -z "$debug_file" ]; then
    # No debug report — check any markdown for the pattern
    debug_file=$(has_section "$OUTPUT_DIR" "root.cause\|Root.Cause")
    if [ -z "$debug_file" ]; then
      ISSUES+=("DEBUGGER: No root cause section found in output (violates 'NEVER guess at fixes')")
      return
    fi
  fi

  # Check that root cause appears before fix
  local rc_line fix_line
  rc_line=$(grep -ni "root.cause\|Root.Cause" "$debug_file" 2>/dev/null | head -1 | cut -d: -f1)
  fix_line=$(grep -ni "^#.*fix\|^#.*solution\|^#.*resolution" "$debug_file" 2>/dev/null | head -1 | cut -d: -f1)

  if [ -n "$fix_line" ] && [ -n "$rc_line" ]; then
    if [ "$fix_line" -lt "$rc_line" ]; then
      ISSUES+=("DEBUGGER: Fix section (line $fix_line) appears before root cause (line $rc_line) in $debug_file")
    fi
  elif [ -n "$fix_line" ] && [ -z "$rc_line" ]; then
    ISSUES+=("DEBUGGER: Fix section found but no root cause section in $debug_file (violates 'NEVER guess at fixes')")
  fi
}

# ── Dispatch to agent-specific audit ──────────────────────────────

if [ ! -d "$OUTPUT_DIR" ]; then
  echo "WARN: Output directory '$OUTPUT_DIR' does not exist. Passing audit (fail-open)." >&2
  exit 0
fi

case "$AGENT" in
  IMPLEMENTER)     audit_implementer ;;
  GATEKEEPER)      audit_gatekeeper ;;
  DEBUGGER)        audit_debugger ;;
  *)               exit 0 ;;  # Default: PASS
esac

# ── Report results ────────────────────────────────────────────────

if [ ${#ISSUES[@]} -eq 0 ]; then
  exit 0
else
  echo "AUDIT FAILED — ${#ISSUES[@]} issue(s):"
  for issue in "${ISSUES[@]}"; do
    echo "  - $issue"
  done
  exit 1
fi
