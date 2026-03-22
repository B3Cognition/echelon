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
VERDICTS=""
CHECKPOINT_REPORT=""
JOURNAL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec)       SPEC="$2"; shift 2 ;;
    --output)     OUTPUT="$2"; shift 2 ;;
    --agent)      AGENT="$2"; shift 2 ;;
    --tier)       TIER="$2"; shift 2 ;;
    --verdicts)   VERDICTS="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT_REPORT="$2"; shift 2 ;;
    --journal)    JOURNAL="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$SPEC" ] || [ -z "$OUTPUT" ]; then
  cat >&2 <<'USAGE'
Usage: int-measure.sh --spec <spec.md> --output <agent-output.md> [options]

Required:
  --spec <file>       Specification with FR-*/NFR-* IDs, constraints, glossary
  --output <file>     Agent output to measure

Optional:
  --agent <name>      Agent codename (default: UNKNOWN)
  --tier <tier>       deep|moderate|minimal|exempt (default: deep)
  --verdicts <file>   Build verdicts for deferred metrics I-09..I-14
                      Format: "TASK_ID GATE VERDICT CYCLE" per line
  --checkpoint <file> CHECKPOINT report for I-10 doubt signal quality
  --journal <file>    reasoning-journal.json for I-12 escalation precision
USAGE
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

# ── Deferred metrics: I-15, I-16 always run (spec+output only) ───────────────

i15=$("$SCRIPT_DIR/i15-decision-traceability.sh" "$SPEC" "$OUTPUT")
i16=$("$SCRIPT_DIR/i16-priority-alignment.sh" "$SPEC" "$OUTPUT")
s15=$(extract_score "$i15")
s16=$(extract_score "$i16")

# ── Deferred metrics: I-09 to I-14 need verdict data ────────────────────────

if [ -n "$VERDICTS" ] && [ -f "$VERDICTS" ]; then
  i09=$("$SCRIPT_DIR/i09-confidence-accuracy.sh" "$SPEC" "$OUTPUT" "$VERDICTS")
  i11=$("$SCRIPT_DIR/i11-blind-spot-rate.sh" "$SPEC" "$OUTPUT" "$VERDICTS")
  i13=$("$SCRIPT_DIR/i13-first-pass-acceptance.sh" "$SPEC" "$OUTPUT" "$VERDICTS")
  i14=$("$SCRIPT_DIR/i14-rework-severity.sh" "$SPEC" "$OUTPUT" "$VERDICTS")
else
  i09='{"metric":"I-09","name":"confidence_accuracy","score":null,"reason":"no-verdicts-file"}'
  i11='{"metric":"I-11","name":"blind_spot_rate","score":null,"reason":"no-verdicts-file"}'
  i13='{"metric":"I-13","name":"first_pass_acceptance","score":null,"reason":"no-verdicts-file"}'
  i14='{"metric":"I-14","name":"rework_severity","score":null,"reason":"no-verdicts-file"}'
fi

if [ -n "$CHECKPOINT_REPORT" ] && [ -f "$CHECKPOINT_REPORT" ] && [ -n "$VERDICTS" ] && [ -f "$VERDICTS" ]; then
  i10=$("$SCRIPT_DIR/i10-doubt-signal-quality.sh" "$SPEC" "$CHECKPOINT_REPORT" "$VERDICTS")
else
  i10='{"metric":"I-10","name":"doubt_signal_quality","score":null,"reason":"no-checkpoint-or-verdicts"}'
fi

if [ -n "$JOURNAL" ] && [ -f "$JOURNAL" ] && [ -n "$VERDICTS" ] && [ -f "$VERDICTS" ]; then
  i12=$("$SCRIPT_DIR/i12-escalation-precision.sh" "$SPEC" "$JOURNAL" "$VERDICTS")
else
  i12='{"metric":"I-12","name":"escalation_precision","score":null,"reason":"no-journal-or-verdicts"}'
fi

s09=$(extract_score "$i09")
s10=$(extract_score "$i10")
s11=$(extract_score "$i11")
s12=$(extract_score "$i12")
s13=$(extract_score "$i13")
s14=$(extract_score "$i14")

calibration=$(compute_mean "$s09" "$s10" "$s11" "$s12")
transfer=$(compute_mean "$s13" "$s14" "$s15" "$s16")

# ── CV-1 (deferred — needs I-13) ────────────────────────────────────────────

if [ "$s01" != "null" ] && [ "$s13" != "null" ]; then
  cv1=$(awk "BEGIN {print ($s01 >= 0.90 && $s13 < 0.50) ? 1 : 0}")
  if [ "$cv1" -eq 1 ]; then
    cv_flags="${cv_flags}\"high-coverage-low-acceptance (I-01=$s01, I-13=$s13)\","
  fi
fi
cv_flags=$(echo "$cv_flags" | sed 's/,$//')

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
      "I-09": $i09,
      "I-10": $i10,
      "I-11": $i11,
      "I-12": $i12,
      "I-13": $i13,
      "I-14": $i14,
      "I-15": $i15,
      "I-16": $i16
    }
  },
  "category_scores": {
    "int_absorption": $absorption,
    "int_accuracy": $accuracy,
    "int_calibration": $calibration,
    "int_transfer": $transfer
  },
  "gate": $gate,
  "cross_validation_flags": [$cv_flags]
}
ENDJSON
