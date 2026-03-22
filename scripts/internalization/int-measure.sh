#!/usr/bin/env bash
# int-measure.sh — Run all 16 deterministic internalization metrics
#
# Usage:
#   ./int-measure.sh --spec <spec.md> --output <agent-output.md> [--agent <name>] [--tier <deep|moderate|minimal|exempt>]
#
# Output: JSON with all metric scores, category scores, gate verdict
#
# All metrics are deterministic: same input → same output, every time.
# No LLM inference. No NLP. Pure regex + set operations + arithmetic.

export LC_NUMERIC=C
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Parse arguments
SPEC=""
OUTPUT=""
AGENT="UNKNOWN"
TIER="deep"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec)   SPEC="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --agent)  AGENT="$2"; shift 2 ;;
    --tier)   TIER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$SPEC" ] || [ -z "$OUTPUT" ]; then
  echo "Usage: int-measure.sh --spec <spec.md> --output <agent-output.md> [--agent <name>] [--tier <deep|moderate|minimal|exempt>]" >&2
  exit 1
fi

if [ ! -f "$SPEC" ]; then echo "Spec not found: $SPEC" >&2; exit 1; fi
if [ ! -f "$OUTPUT" ]; then echo "Output not found: $OUTPUT" >&2; exit 1; fi

# ── Run all 8 immediate metrics ──────────────────────────────────────────────

i01=$("$SCRIPT_DIR/i01-requirement-coverage.sh" "$SPEC" "$OUTPUT")
i02=$("$SCRIPT_DIR/i02-constraint-adherence.sh" "$SPEC" "$OUTPUT")
i03=$("$SCRIPT_DIR/i03-terminology-fidelity.sh" "$SPEC" "$OUTPUT")
i04=$("$SCRIPT_DIR/i04-dependency-awareness.sh" "$SPEC" "$OUTPUT")
i05=$("$SCRIPT_DIR/i05-numeric-contradiction.sh" "$SPEC" "$OUTPUT")
i06=$("$SCRIPT_DIR/i06-uncited-decision.sh" "$SPEC" "$OUTPUT")
i07=$("$SCRIPT_DIR/i07-cross-reference-accuracy.sh" "$SPEC" "$OUTPUT")
i08=$("$SCRIPT_DIR/i08-keyword-scope.sh" "$SPEC" "$OUTPUT")

# ── Extract scores (handle null) ─────────────────────────────────────────────

extract_score() {
  echo "$1" | grep -oE '"score":[0-9.]+' | head -1 | cut -d: -f2 || echo "null"
}

s01=$(extract_score "$i01")
s02=$(extract_score "$i02")
s03=$(extract_score "$i03")
s04=$(extract_score "$i04")
s05=$(extract_score "$i05")
s06=$(extract_score "$i06")
s07=$(extract_score "$i07")
s08=$(extract_score "$i08")

# ── Compute category scores (mean of non-null) ──────────────────────────────

compute_mean() {
  local scores=("$@")
  local sum=0
  local count=0
  for s in "${scores[@]}"; do
    if [ "$s" != "null" ] && [ -n "$s" ]; then
      sum=$(awk "BEGIN {print $sum + $s}")
      count=$((count + 1))
    fi
  done
  if [ "$count" -eq 0 ]; then
    echo "null"
  else
    awk "BEGIN {printf \"%.4f\", $sum / $count}"
  fi
}

absorption=$(compute_mean "$s01" "$s02" "$s03" "$s04")
accuracy=$(compute_mean "$s05" "$s06" "$s07" "$s08")

# ── Gate evaluation ──────────────────────────────────────────────────────────

gate=$("$SCRIPT_DIR/int-gate.sh" "$absorption" "$accuracy" "$TIER")

# ── Cross-validation (immediate rules only) ──────────────────────────────────

cv_flags=""

# CV-2: high terminology (I-03 >= 0.90) but low accuracy (I-05 < 0.80)
if [ "$s03" != "null" ] && [ "$s05" != "null" ]; then
  cv2=$(awk "BEGIN {print ($s03 >= 0.90 && $s05 < 0.80) ? 1 : 0}")
  if [ "$cv2" -eq 1 ]; then
    cv_flags="${cv_flags}\"high-terminology-low-accuracy (I-03=$s03, I-05=$s05)\","
  fi
fi

# CV-3: high coverage (I-01 >= 0.90) but low terminology (I-03 < 0.40)
if [ "$s01" != "null" ] && [ "$s03" != "null" ]; then
  cv3=$(awk "BEGIN {print ($s01 >= 0.90 && $s03 < 0.40) ? 1 : 0}")
  if [ "$cv3" -eq 1 ]; then
    cv_flags="${cv_flags}\"citation-stuffing-low-fidelity (I-01=$s01, I-03=$s03)\","
  fi
fi

cv_flags=$(echo "$cv_flags" | sed 's/,$//')
if [ -z "$cv_flags" ]; then cv_flags=""; fi

# ── Deferred metrics placeholder ─────────────────────────────────────────────
# I-09 to I-16 require verdict data from build phase.
# They are null until downstream outcome data is available.

# ── Assemble final JSON ──────────────────────────────────────────────────────

cat <<ENDJSON
{
  "agent": "$AGENT",
  "tier": "$TIER",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "metrics": {
    "immediate": {
      "I-01": $i01,
      "I-02": $i02,
      "I-03": $i03,
      "I-04": $i04,
      "I-05": $i05,
      "I-06": $i06,
      "I-07": $i07,
      "I-08": $i08
    },
    "deferred": {
      "I-09": {"metric":"I-09","name":"confidence_accuracy","score":null,"reason":"requires-verdict-data"},
      "I-10": {"metric":"I-10","name":"doubt_signal_quality","score":null,"reason":"requires-verdict-data"},
      "I-11": {"metric":"I-11","name":"blind_spot_rate","score":null,"reason":"requires-verdict-data"},
      "I-12": {"metric":"I-12","name":"escalation_precision","score":null,"reason":"requires-verdict-data"},
      "I-13": {"metric":"I-13","name":"first_pass_acceptance","score":null,"reason":"requires-verdict-data"},
      "I-14": {"metric":"I-14","name":"rework_severity","score":null,"reason":"requires-verdict-data"},
      "I-15": {"metric":"I-15","name":"decision_traceability","score":null,"reason":"requires-verdict-data"},
      "I-16": {"metric":"I-16","name":"priority_alignment","score":null,"reason":"requires-verdict-data"}
    }
  },
  "category_scores": {
    "int_absorption": $absorption,
    "int_accuracy": $accuracy,
    "int_calibration": null,
    "int_transfer": null
  },
  "gate": $gate,
  "cross_validation_flags": [$cv_flags]
}
ENDJSON
