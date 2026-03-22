#!/usr/bin/env bash
# Int-Gate: evaluate gate verdict from metric scores
# Formula: PASS if absorption >= threshold AND accuracy >= threshold
# Inputs: $1=absorption_score, $2=accuracy_score, $3=tier (deep|moderate|minimal|exempt)
export LC_NUMERIC=C
set -euo pipefail

ABSORPTION="${1:-null}"
ACCURACY="${2:-null}"
TIER="${3:-deep}"

# Tier thresholds (matching config-template.yml)
case "$TIER" in
  deep)     abs_thresh=0.80; acc_thresh=0.75 ;;
  moderate) abs_thresh=0.65; acc_thresh=0.60 ;;
  minimal)  abs_thresh=0.40; acc_thresh=0.40 ;;
  exempt)
    echo "{\"verdict\":\"EXEMPT\",\"tier\":\"exempt\",\"absorption\":$ABSORPTION,\"accuracy\":$ACCURACY}"
    exit 0 ;;
  *)        abs_thresh=0.80; acc_thresh=0.75 ;; # default to deep
esac

if [ "$ABSORPTION" = "null" ] && [ "$ACCURACY" = "null" ]; then
  echo "{\"verdict\":\"INSUFFICIENT_DATA\",\"tier\":\"$TIER\",\"absorption\":null,\"accuracy\":null}"
  exit 0
fi

abs_pass=$(awk "BEGIN {print ($ABSORPTION >= $abs_thresh) ? 1 : 0}" 2>/dev/null || echo 0)
acc_pass=$(awk "BEGIN {print ($ACCURACY >= $acc_thresh) ? 1 : 0}" 2>/dev/null || echo 0)

if [ "$abs_pass" -eq 1 ] && [ "$acc_pass" -eq 1 ]; then
  verdict="PASS"
else
  verdict="FAIL"
fi

failing=""
if [ "$abs_pass" -eq 0 ]; then
  shortfall=$(awk "BEGIN {printf \"%.4f\", $abs_thresh - $ABSORPTION}")
  failing="${failing}\"absorption (${ABSORPTION} < ${abs_thresh}, shortfall: ${shortfall})\","
fi
if [ "$acc_pass" -eq 0 ]; then
  shortfall=$(awk "BEGIN {printf \"%.4f\", $acc_thresh - $ACCURACY}")
  failing="${failing}\"accuracy (${ACCURACY} < ${acc_thresh}, shortfall: ${shortfall})\","
fi
failing=$(echo "$failing" | sed 's/,$//')

echo "{\"verdict\":\"$verdict\",\"tier\":\"$TIER\",\"absorption\":$ABSORPTION,\"accuracy\":$ACCURACY,\"abs_threshold\":$abs_thresh,\"acc_threshold\":$acc_thresh,\"failing\":[$failing]}"
