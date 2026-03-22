#!/usr/bin/env bash
# generate-mock-run.sh — Generate RADAR mock data simulating a complete squad run
#
# Usage:
#   ./generate-mock-run.sh [--output-dir <dir>] [--run-id <id>] [--realtime]
#
# Generates:
#   agent-states.json      — Final snapshot (all agents complete)
#   agent-states-events.jsonl — Time-ordered event log (22 events)
#   state.json             — Squad state with quality scores, issues, internalization
#
# With --realtime: writes events with realistic delays (for live FE testing)
# Without --realtime: writes all events instantly (for fixture generation)
export LC_NUMERIC=C
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OUTPUT_DIR="$REPO_ROOT/.specify/squad"
RUN_ID="squad-mock-$(date +%s)"
REALTIME=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --run-id)     RUN_ID="$2"; shift 2 ;;
    --realtime)   REALTIME=true; shift ;;
    *)            echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$OUTPUT_DIR"

# ── Helpers ──────────────────────────────────────────────────────────────────

NOW_EPOCH=$(date +%s)
OFFSET=0

ts() {
  local epoch=$((NOW_EPOCH + OFFSET))
  python3 -c "from datetime import datetime, timezone; print(datetime.fromtimestamp($epoch, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000000Z'))"
}

emit_dispatch() {
  local id="$1" codename="$2" phase="$3"
  local timestamp=$(ts)

  # Append to JSONL
  echo "{\"id\":\"$id\",\"codename\":\"$codename\",\"state\":\"working\",\"ts\":\"$timestamp\",\"phase\":\"$phase\",\"run_id\":\"$RUN_ID\"}" >> "$OUTPUT_DIR/agent-states-events.jsonl"

  # Update snapshot
  python3 -c "
import json
with open('$OUTPUT_DIR/agent-states.json') as f: snap = json.load(f)
snap['agents']['$id'] = {
    'id': '$id', 'codename': '$codename', 'state': 'working',
    'phase': '$phase', 'run_id': '$RUN_ID',
    'dispatched_at': '$timestamp', 'completed_at': None,
    'artifacts_produced': [], 'blocked_reason': None
}
if '$id' not in snap['dispatch_order']: snap['dispatch_order'].append('$id')
snap['updated_at'] = '$timestamp'
with open('$OUTPUT_DIR/agent-states.json', 'w') as f: json.dump(snap, f, indent=2)
"
  echo "  ⏵ $codename ($id) dispatched → $phase"
}

emit_complete() {
  local id="$1" codename="$2" phase="$3" duration="$4"
  shift 4
  local artifacts=("$@")

  OFFSET=$((OFFSET + duration))
  local timestamp=$(ts)

  # Build artifacts JSON array
  local artifacts_json=$(printf '"%s",' "${artifacts[@]}" | sed 's/,$//')

  # Append to JSONL
  echo "{\"id\":\"$id\",\"codename\":\"$codename\",\"state\":\"complete\",\"ts\":\"$timestamp\",\"phase\":\"$phase\",\"run_id\":\"$RUN_ID\",\"artifacts_produced\":[$artifacts_json]}" >> "$OUTPUT_DIR/agent-states-events.jsonl"

  # Update snapshot
  python3 -c "
import json
with open('$OUTPUT_DIR/agent-states.json') as f: snap = json.load(f)
snap['agents']['$id']['state'] = 'complete'
snap['agents']['$id']['completed_at'] = '$timestamp'
snap['agents']['$id']['artifacts_produced'] = [$artifacts_json]
snap['updated_at'] = '$timestamp'
with open('$OUTPUT_DIR/agent-states.json', 'w') as f: json.dump(snap, f, indent=2)
"
  echo "  ✓ $codename ($id) complete → ${duration}s, ${#artifacts[@]} artifacts"

  if $REALTIME; then sleep "$duration"; fi
}

emit_error() {
  local id="$1" codename="$2" phase="$3" duration="$4"
  OFFSET=$((OFFSET + duration))
  local timestamp=$(ts)

  echo "{\"id\":\"$id\",\"codename\":\"$codename\",\"state\":\"error\",\"ts\":\"$timestamp\",\"phase\":\"$phase\",\"run_id\":\"$RUN_ID\"}" >> "$OUTPUT_DIR/agent-states-events.jsonl"

  python3 -c "
import json
with open('$OUTPUT_DIR/agent-states.json') as f: snap = json.load(f)
snap['agents']['$id']['state'] = 'error'
snap['agents']['$id']['completed_at'] = '$timestamp'
snap['updated_at'] = '$timestamp'
with open('$OUTPUT_DIR/agent-states.json', 'w') as f: json.dump(snap, f, indent=2)
"
  echo "  ✗ $codename ($id) error → ${duration}s"
}

# ── Initialize ───────────────────────────────────────────────────────────────

echo "═══════════════════════════════════════"
echo "  RADAR Mock Run: $RUN_ID"
echo "  Output: $OUTPUT_DIR"
echo "  Mode: $(if $REALTIME; then echo 'REALTIME (with delays)'; else echo 'INSTANT'; fi)"
echo "═══════════════════════════════════════"
echo ""

# Init files
echo '{"run_id":"'"$RUN_ID"'","updated_at":"'"$(ts)"'","agents":{},"dispatch_order":[]}' > "$OUTPUT_DIR/agent-states.json"
> "$OUTPUT_DIR/agent-states-events.jsonl"

# ── Phase 1: DISCOVER ────────────────────────────────────────────────────────

echo "Phase: DISCOVER"
emit_dispatch "SCOUT-1" "SCOUT" "discover"
if $REALTIME; then sleep 2; fi
emit_complete "SCOUT-1" "SCOUT" "discover" 472 \
  "glossary.md" "mental-model.md" "boundaries.md" "assumptions.md" "unknowns.md" "reference-architectures.md"

OFFSET=$((OFFSET + 5))
emit_dispatch "SYNTHESIZER-1" "SYNTHESIZER" "discover"
if $REALTIME; then sleep 2; fi
emit_complete "SYNTHESIZER-1" "SYNTHESIZER" "discover" 645 \
  "glossary.md" "mental-model.md" "boundaries.md" "assumptions.md" "unknowns.md" "contradictions-and-gaps.md" "risks.md"

OFFSET=$((OFFSET + 3))
emit_dispatch "TRACKER-1" "TRACKER" "discover"
if $REALTIME; then sleep 1; fi
emit_complete "TRACKER-1" "TRACKER" "discover" 91 "user-intent.md"

# ── Phase 2: WHY1 ────────────────────────────────────────────────────────────

echo ""
echo "Phase: WHY1"
OFFSET=$((OFFSET + 5))
emit_dispatch "SAGE-1" "SAGE" "why1"
if $REALTIME; then sleep 2; fi
emit_complete "SAGE-1" "SAGE" "why1" 387 \
  "assumption-review.md" "unknowns.md" "issues.md"

# ── Phase 3: WHAT ────────────────────────────────────────────────────────────

echo ""
echo "Phase: WHAT"
OFFSET=$((OFFSET + 10))
emit_dispatch "CARTOGRAPHER-1" "CARTOGRAPHER" "what"
if $REALTIME; then sleep 2; fi
emit_complete "CARTOGRAPHER-1" "CARTOGRAPHER" "what" 202 \
  "spec.md" "00-overview.md"

# ── Phase 4: WHY2 ────────────────────────────────────────────────────────────

echo ""
echo "Phase: WHY2"
OFFSET=$((OFFSET + 5))
emit_dispatch "SAGE-2" "SAGE" "why2"
if $REALTIME; then sleep 1; fi
emit_complete "SAGE-2" "SAGE" "why2" 135 \
  "issues.md" "quality-gates.md"

# ── Phase 5: ASSESS ──────────────────────────────────────────────────────────

echo ""
echo "Phase: ASSESS"
OFFSET=$((OFFSET + 5))
emit_dispatch "GATEKEEPER-1" "GATEKEEPER" "assess"
if $REALTIME; then sleep 2; fi
emit_complete "GATEKEEPER-1" "GATEKEEPER" "assess" 249 \
  "feasibility.md" "estimates.md" "mvp-scope.md"

# ── Phase 6: HOW + PLAN ─────────────────────────────────────────────────────

echo ""
echo "Phase: HOW + PLAN"
OFFSET=$((OFFSET + 5))
emit_dispatch "ARCHITECT-1" "ARCHITECT" "how"
if $REALTIME; then sleep 2; fi
emit_complete "ARCHITECT-1" "ARCHITECT" "how" 249 \
  "research.md" "plan.md" "data-model.md"

OFFSET=$((OFFSET + 3))
emit_dispatch "ORCHESTRATOR-1" "ORCHESTRATOR" "plan"
if $REALTIME; then sleep 2; fi
emit_complete "ORCHESTRATOR-1" "ORCHESTRATOR" "plan" 249 \
  "tasks.md" "critical-path.md"

# ── Phase 7: FINALIZE ────────────────────────────────────────────────────────

echo ""
echo "Phase: FINALIZE"
OFFSET=$((OFFSET + 5))
emit_dispatch "REALIST-1" "REALIST" "finalize"
if $REALTIME; then sleep 1; fi
emit_complete "REALIST-1" "REALIST" "finalize" 210 "reality-check.md"

OFFSET=$((OFFSET + 3))
emit_dispatch "AUDITOR-1" "AUDITOR" "finalize"
if $REALTIME; then sleep 1; fi
emit_complete "AUDITOR-1" "AUDITOR" "finalize" 210 "confidence-flags.md"

# ── Copy state.json mock ─────────────────────────────────────────────────────

cp "$REPO_ROOT/tests/fixtures/radar/mock-state.json" "$OUTPUT_DIR/state.json" 2>/dev/null || true
# Update run_id in state.json
python3 -c "
import json
try:
    with open('$OUTPUT_DIR/state.json') as f: s = json.load(f)
    s['run_id'] = '$RUN_ID'
    with open('$OUTPUT_DIR/state.json', 'w') as f: json.dump(s, f, indent=2)
except: pass
"

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════"
echo "  Mock run complete"
echo "  Events: $(wc -l < "$OUTPUT_DIR/agent-states-events.jsonl" | tr -d ' ') events"
echo "  Agents: $(python3 -c "import json; print(len(json.load(open('$OUTPUT_DIR/agent-states.json'))['agents']))")"
echo "  Duration: ${OFFSET}s simulated"
echo ""
echo "  Files:"
echo "    $OUTPUT_DIR/agent-states.json"
echo "    $OUTPUT_DIR/agent-states-events.jsonl"
echo "    $OUTPUT_DIR/state.json"
echo "═══════════════════════════════════════"
