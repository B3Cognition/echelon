#!/usr/bin/env bash
# Belief freshness check — called by COMMANDER at run start
# Reads config-belief-graph.json and warns about stale beliefs
# Exit 0 always (never blocks the run per FR-009)
#
# Usage: ./scripts/bash/belief-freshness-check.sh [--belief-graph PATH]
# Default graph path: config-belief-graph.json (repo root)

set -uo pipefail

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
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"

if [ -z "$BELIEF_GRAPH" ]; then
  BELIEF_GRAPH="$REPO_ROOT/config-belief-graph.json"
fi

# ── FR-010: Missing graph — exit silently ─────────────────────────

if [ ! -f "$BELIEF_GRAPH" ]; then
  exit 0
fi

# ── Python3 availability check ────────────────────────────────────

if ! command -v python3 &>/dev/null; then
  echo "WARN: python3 not found — belief freshness check skipped." >&2
  exit 0
fi

# ── Core analysis via python3 ─────────────────────────────────────

python3 - "$BELIEF_GRAPH" <<'PYEOF'
import sys
import json
from datetime import date, timedelta

BELIEF_GRAPH = sys.argv[1]
LOW_CONFIDENCE_THRESHOLD = 0.50
APPROACHING_EXPIRY_DAYS  = 30

# ── Load and validate ─────────────────────────────────────────────

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
stale_beliefs  = []   # list of (belief_dict, derived_status)

for belief in beliefs:
    belief_id  = belief.get("belief_id", "<unknown>")
    claim      = belief.get("claim", "")
    confidence = float(belief.get("confidence", 1.0))
    severity   = belief.get("severity", "medium")
    source_file = belief.get("source_file", "")
    source_line = belief.get("source_line", "")
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
        # Unknown status — treat as stale
        derived_status = raw_status

    stale_beliefs.append({
        "belief_id":   belief_id,
        "claim":       claim,
        "confidence":  confidence,
        "severity":    severity,
        "source_file": source_file,
        "source_line": source_line,
        "status":      derived_status,
    })

# Beliefs classified as stale and fresh above; count any remaining fresh
# (approaching_expiry and expired ones are in stale_beliefs already)
# Recount: fresh = total - stale
fresh_count = len(beliefs) - len(stale_beliefs)

# ── Emit per-belief warnings ──────────────────────────────────────

CRITICAL_BANNER_TOP    = "╔══════════════════════════════════════════════╗"
CRITICAL_BANNER_SEP    = "╠══════════════════════════════════════════════╣"
CRITICAL_BANNER_BOTTOM = "╚══════════════════════════════════════════════╝"

critical_stale = [b for b in stale_beliefs if b["severity"] == "critical"]
non_critical_stale = [b for b in stale_beliefs if b["severity"] != "critical"]

# Emit non-critical stale warnings first
for b in non_critical_stale:
    source = f"{b['source_file']}:{b['source_line']}" if b['source_file'] else "<unknown>"
    print(f"\u26a0 STALE BELIEF: {b['belief_id']}")
    print(f"  Claim: {b['claim']}")
    print(f"  Status: {b['status']}")
    print(f"  Confidence: {b['confidence']}")
    print(f"  Source: {source}")

# FR-011: Critical stale beliefs get a prominent banner
for b in critical_stale:
    source = f"{b['source_file']}:{b['source_line']}" if b['source_file'] else "<unknown>"
    print(CRITICAL_BANNER_TOP)
    print("║  CRITICAL STALE BELIEF DETECTED             ║")
    print(CRITICAL_BANNER_SEP)

    # Pad lines to fit banner width (44 visible chars between ║  and  ║)
    def banner_line(text, width=44):
        padded = text[:width]
        return f"║  {padded:<{width}}║"

    print(banner_line(b["belief_id"]))
    # Truncate claim to 44 chars for display
    claim_display = b["claim"] if len(b["claim"]) <= 44 else b["claim"][:41] + "..."
    print(banner_line(claim_display))
    status_conf = f"Status: {b['status']} | Confidence: {b['confidence']}"
    print(banner_line(status_conf))
    print(CRITICAL_BANNER_BOTTOM)
    # Also emit the structured warning for tooling/log parsing
    print(f"\u26a0 STALE BELIEF: {b['belief_id']}")
    print(f"  Claim: {b['claim']}")
    print(f"  Status: {b['status']}")
    print(f"  Confidence: {b['confidence']}")
    print(f"  Source: {source}")

# ── Summary line ──────────────────────────────────────────────────

critical_count = len(critical_stale)
stale_count    = len(stale_beliefs)

print(f"Belief freshness: {fresh_count} fresh, {stale_count} stale ({critical_count} critical)")

sys.exit(0)
PYEOF

# The python3 heredoc exits 0 always; propagate that
exit 0
