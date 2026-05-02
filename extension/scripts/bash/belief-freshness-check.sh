#!/usr/bin/env bash
# Belief freshness check — called by COMMANDER at run start
# Reads config-belief-graph.json, classifies beliefs, and exits with graduated codes.
#
# EXIT CODES (FR-001):
#   0 = all fresh, or graph missing/unparseable (backward compatible)
#   1 = high-severity stale beliefs OR 3+ low-confidence beliefs (defer dispatch)
#   2 = critical-severity stale beliefs detected (dispatch INVESTIGATOR)
#
# When exit code is non-zero, structured JSON is written to stdout (FR-002).
#
# Usage: ./scripts/bash/belief-freshness-check.sh [--belief-graph PATH]
# Default graph path: config-belief-graph.json (repo root)

set -uo pipefail
. "$(CDPATH='' cd "$(dirname -- "$0")" && pwd)/python-detect.sh"

# ── Argument parsing ──────────────────────────────────────────────

BELIEF_GRAPH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --belief-graph) BELIEF_GRAPH="$2"; shift 2 ;;
    *) echo "WARN: Unknown option: $1" >&2; shift ;;
  esac
done

# Resolve default path relative to repo root (two dirs up from scripts/bash/)
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)"

if [ -z "$BELIEF_GRAPH" ]; then
  BELIEF_GRAPH="$REPO_ROOT/config-belief-graph.json"
fi

# ── FR-010: Missing graph — exit silently ─────────────────────────

if [ ! -f "$BELIEF_GRAPH" ]; then
  exit 0
fi

# ── Python3 availability check ────────────────────────────────────

if ! command -v $PYTHON &>/dev/null; then
  echo "WARN: $PYTHON not found — belief freshness check skipped." >&2
  exit 0
fi

# ── Core analysis via $PYTHON ─────────────────────────────────────

$PYTHON - "$BELIEF_GRAPH" <<'PYEOF'
import sys
import json
from datetime import date

BELIEF_GRAPH = sys.argv[1]
LOW_CONFIDENCE_THRESHOLD = 0.50
APPROACHING_EXPIRY_DAYS  = 30

# ── Load and validate (FR-010: missing/malformed → exit 0) ───────

try:
    with open(BELIEF_GRAPH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except (json.JSONDecodeError, OSError) as exc:
    print(f"WARN: Could not parse belief graph ({exc}) — freshness check skipped.", file=sys.stderr)
    sys.exit(0)

beliefs = data.get("beliefs", [])
if not isinstance(beliefs, list):
    print("WARN: belief graph 'beliefs' field is not a list — freshness check skipped.", file=sys.stderr)
    sys.exit(0)

today = date.today()

# ── Classify each belief ──────────────────────────────────────────

fresh_count    = 0
stale_beliefs  = []

for belief in beliefs:
    belief_id   = belief.get("belief_id", "<unknown>")
    claim       = belief.get("claim", "")
    confidence  = float(belief.get("confidence", 1.0))
    severity    = belief.get("severity", "medium")
    source_file = belief.get("source_file", "")
    source_line = belief.get("source_line", "")
    config_key  = belief.get("config_key", "")
    raw_status  = belief.get("status", "fresh")

    expires_str = belief.get("expires_date") or ""
    expires = None
    if expires_str:
        try:
            expires = date.fromisoformat(expires_str)
        except ValueError:
            pass

    # Determine derived status
    if raw_status == "low_confidence" or confidence < LOW_CONFIDENCE_THRESHOLD:
        derived_status = "low_confidence"
    elif expires and expires < today:
        derived_status = "expired"
    elif expires and (expires - today).days <= APPROACHING_EXPIRY_DAYS:
        derived_status = "approaching_expiry"
    elif raw_status == "fresh":
        fresh_count += 1
        continue
    else:
        derived_status = raw_status

    stale_beliefs.append({
        "belief_id":            belief_id,
        "claim":                claim,
        "confidence":           confidence,
        "severity":             severity,
        "source_file":          source_file,
        "source_line":          source_line,
        "status":               derived_status,
        "dependent_config_key": config_key,
    })

fresh_count = len(beliefs) - len(stale_beliefs)

# ── Determine graduated exit code (FR-001, FR-008, FR-011) ───────

critical_stale     = [b for b in stale_beliefs if b["severity"] == "critical" and b["status"] == "expired"]
high_stale         = [b for b in stale_beliefs if b["severity"] == "high" and b["status"] == "expired"]
low_confidence_all = [b for b in stale_beliefs if b["status"] == "low_confidence"]

if critical_stale:
    exit_code = 2  # Critical-severity expired → INVESTIGATOR dispatch
elif high_stale or len(low_confidence_all) >= 3:
    exit_code = 1  # High-severity expired OR 3+ low-confidence → defer dispatch
else:
    exit_code = 0  # All others (approaching_expiry, low/medium expired) → log only

# ── Emit human-readable warnings to stderr ────────────────────────

CRITICAL_BANNER_TOP    = "╔══════════════════════════════════════════════╗"
CRITICAL_BANNER_SEP    = "╠══════════════════════════════════════════════╣"
CRITICAL_BANNER_BOTTOM = "╚══════════════════════════════════════════════╝"

non_critical_stale = [b for b in stale_beliefs if not (b["severity"] == "critical" and b["status"] == "expired")]

for b in non_critical_stale:
    source = f"{b['source_file']}:{b['source_line']}" if b['source_file'] else "<unknown>"
    print(f"\u26a0 STALE BELIEF: {b['belief_id']}", file=sys.stderr)
    print(f"  Claim: {b['claim']}", file=sys.stderr)
    print(f"  Status: {b['status']} | Severity: {b['severity']} | Confidence: {b['confidence']}", file=sys.stderr)
    print(f"  Source: {source}", file=sys.stderr)

for b in critical_stale:
    source = f"{b['source_file']}:{b['source_line']}" if b['source_file'] else "<unknown>"
    print(CRITICAL_BANNER_TOP, file=sys.stderr)
    print("║  CRITICAL STALE BELIEF — INVESTIGATION REQ  ║", file=sys.stderr)
    print(CRITICAL_BANNER_SEP, file=sys.stderr)
    def banner_line(text, width=44):
        padded = text[:width]
        return f"║  {padded:<{width}}║"
    print(banner_line(b["belief_id"]), file=sys.stderr)
    claim_display = b["claim"] if len(b["claim"]) <= 44 else b["claim"][:41] + "..."
    print(banner_line(claim_display), file=sys.stderr)
    print(CRITICAL_BANNER_BOTTOM, file=sys.stderr)

# ── Summary to stderr ─────────────────────────────────────────────

stale_count    = len(stale_beliefs)
critical_count = len(critical_stale)
print(f"Belief freshness: {fresh_count} fresh, {stale_count} stale ({critical_count} critical) → exit {exit_code}", file=sys.stderr)

# ── Structured JSON to stdout when non-zero (FR-002) ─────────────

if exit_code > 0:
    recommended = "investigate" if exit_code == 2 else "defer"
    output = {
        "exit_code": exit_code,
        "recommended_action": recommended,
        "stale_beliefs": [
            {
                "belief_id":            b["belief_id"],
                "claim":                b["claim"],
                "severity":             b["severity"],
                "confidence":           b["confidence"],
                "status":               b["status"],
                "dependent_config_key": b["dependent_config_key"],
            }
            for b in stale_beliefs
            if b["status"] == "expired" or b["status"] == "low_confidence"
        ],
        "summary": {
            "total_beliefs": len(beliefs),
            "fresh": fresh_count,
            "stale": stale_count,
            "critical_expired": critical_count,
            "high_expired": len(high_stale),
            "low_confidence": len(low_confidence_all),
        },
    }
    print(json.dumps(output, indent=2))

sys.exit(exit_code)
PYEOF

# Propagate the python exit code to the shell
exit $?
