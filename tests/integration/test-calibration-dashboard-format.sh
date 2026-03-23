#!/usr/bin/env bash
# T-34: Integration test — fixture calibration dashboard, validate sections

set -euo pipefail

FIXTURES_DIR="$(dirname "$0")/../fixtures/internalization"
DASHBOARD_FILE="$FIXTURES_DIR/calibration-dashboard-fixture.md"
PASS=0
FAIL=0

assert_true() {
  local label="$1"
  local result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    FAIL=$((FAIL + 1))
  fi
}

assert_section() {
  local label="$1"
  local pattern="$2"
  assert_true "$label" \
    "$(grep -qiE "$pattern" "$DASHBOARD_FILE" && echo true || echo false)"
}

# --- Step 1: Create fixture dashboard ---
echo "=== Integration Test: Calibration Dashboard Format ==="
echo ""
echo "--- Creating fixture dashboard ---"

cat > "$DASHBOARD_FILE" << 'MARKDOWN'
# Calibration Dashboard — Run squad-010-1742652000

Generated: 2026-03-23T14:30:00Z

## Domain Calibration Overview

| Domain | Accuracy | Trend | Correction Factor | Sample Size | Risk Level |
|--------|----------|-------|-------------------|-------------|------------|
| backend | 0.82 | improving | 1.05 | 12 | LOW |
| frontend | 0.61 | declining | 0.85 | 8 | MEDIUM |
| security | 0.45 | stable | 1.30 | 4 | HIGH |
| database | 0.78 | stable | 1.00 | 10 | LOW |
| infrastructure | 0.52 | improving | 1.10 | 6 | MEDIUM |

## Agent Internalization Health

| Agent | Composite | Absorption | Accuracy | Calibration | Transfer | Trend | Phase |
|-------|-----------|------------|----------|-------------|----------|-------|-------|
| ARCHITECT | 0.88 | 0.91 | 0.85 | 0.87 | 0.82 | improving | 3 |
| IMPLEMENTER | 0.62 | 0.70 | 0.58 | null | null | declining | 1 |
| SCOUT | 0.80 | 0.82 | 0.79 | null | null | stable | 2 |
| SPEC_GUARD | null | null | null | null | null | insufficient_data | 1 |

## Cross-Validation Flags

| Agent | Flag | Rule | Triggering Metrics |
|-------|------|------|--------------------|
| IMPLEMENTER | high-terminology-low-accuracy | CV-2 | I-03=0.92, I-05=0.68 |

## Evolution Signals

| Signal ID | Trigger | Severity | Status | Affected Agents |
|-----------|---------|----------|--------|-----------------|
| evo-sig-012 | int_declining_trend | HIGH | open | IMPLEMENTER |
| evo-sig-013 | int_accuracy_drop | MEDIUM | acknowledged | SCOUT |

## Calibration Health Score

```
calibration_health = (3/5) * 0.4 + (2/4) * 0.4 + (1 - 1/2) * 0.2
                   = 0.24 + 0.20 + 0.10
                   = 0.54
```

**Calibration Health: 0.54 (DEGRADED)**

### Summary
- Domains above threshold: 3 / 5
- Agents passing int-gate: 2 / 4
- Open evolution signals: 1 / 2
- Domains at risk: security (HIGH)
- Agents declining: IMPLEMENTER
MARKDOWN

echo "  Fixture written to: $DASHBOARD_FILE"

# --- Step 2: Validate required sections ---
echo ""
echo "--- Validating required sections ---"

assert_section "Title with run ID" \
  "# Calibration Dashboard.*Run"

assert_section "Generation timestamp" \
  "Generated:.*[0-9]{4}-[0-9]{2}-[0-9]{2}"

assert_section "Section: Domain Calibration Overview" \
  "## Domain Calibration Overview"

assert_section "Section: Agent Internalization Health" \
  "## Agent Internalization Health"

assert_section "Section: Cross-Validation Flags" \
  "## Cross-Validation Flags"

assert_section "Section: Evolution Signals" \
  "## Evolution Signals"

assert_section "Section: Calibration Health Score" \
  "## Calibration Health Score"

# --- Step 3: Validate table structures ---
echo ""
echo "--- Validating table structures ---"

# Domain table has required columns
assert_section "Domain table has Accuracy column" \
  "Domain.*Accuracy.*Trend.*Correction Factor"

assert_section "Domain table has Risk Level column" \
  "Risk Level"

# Agent table has required columns
assert_section "Agent table has Composite column" \
  "Agent.*Composite.*Absorption.*Accuracy"

assert_section "Agent table has Trend column" \
  "Trend.*Phase"

# Evolution signals table
assert_section "Evolution signals has Severity column" \
  "Signal ID.*Trigger.*Severity.*Status"

# --- Step 4: Validate risk levels ---
echo ""
echo "--- Validating risk level values ---"

assert_true "LOW risk level present" \
  "$(grep -q '| LOW |' "$DASHBOARD_FILE" && echo true || echo false)"

assert_true "MEDIUM risk level present" \
  "$(grep -q '| MEDIUM |' "$DASHBOARD_FILE" && echo true || echo false)"

assert_true "HIGH risk level present" \
  "$(grep -q '| HIGH |' "$DASHBOARD_FILE" && echo true || echo false)"

# --- Step 5: Validate health score ---
echo ""
echo "--- Validating health score ---"

assert_section "Health score formula shown" \
  "calibration_health ="

assert_section "Health classification present" \
  "Calibration Health:.*HEALTHY|DEGRADED|CRITICAL"

assert_true "Health score is numeric" \
  "$(grep -qE 'Calibration Health: [0-9]+\.[0-9]+' "$DASHBOARD_FILE" && echo true || echo false)"

# --- Step 6: Validate summary section ---
echo ""
echo "--- Validating summary ---"

assert_section "Domains above threshold count" \
  "Domains above threshold:"

assert_section "Agents passing count" \
  "Agents passing"

assert_section "Open evolution signals count" \
  "Open evolution signals:"

assert_section "Domains at risk listed" \
  "Domains at risk:"

assert_section "Agents declining listed" \
  "Agents declining:"

# --- Step 7: Validate null handling ---
echo ""
echo "--- Validating null values ---"

assert_true "null values present in agent table" \
  "$(grep -q '| null |' "$DASHBOARD_FILE" && echo true || echo false)"

assert_true "insufficient_data trend present" \
  "$(grep -q 'insufficient_data' "$DASHBOARD_FILE" && echo true || echo false)"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
