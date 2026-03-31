#!/usr/bin/env bash
# T-40: Unified test runner — runs all unit, integration, and e2e tests
# Reports per-suite results and overall summary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors (disabled if not a terminal)
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  GREEN=''
  RED=''
  YELLOW=''
  BOLD=''
  RESET=''
fi

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
SUITE_RESULTS=()

run_suite() {
  local suite_name="$1"
  local suite_dir="$2"
  local suite_pass=0
  local suite_fail=0
  local suite_skip=0

  printf "\n${BOLD}========== %s ==========${RESET}\n" "$suite_name"

  if [[ ! -d "$suite_dir" ]]; then
    printf "${YELLOW}SKIP: Directory not found: %s${RESET}\n" "$suite_dir"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no directory)")
    return
  fi

  local test_files=()
  while IFS= read -r -d '' file; do
    test_files+=("$file")
  done < <(find "$suite_dir" -maxdepth 1 -name 'test-*.sh' -type f -print0 | sort -z)

  if [[ ${#test_files[@]} -eq 0 ]]; then
    printf "${YELLOW}SKIP: No test files found in %s${RESET}\n" "$suite_dir"
    SUITE_RESULTS+=("$suite_name|0|0|0|SKIPPED (no tests)")
    return
  fi

  for test_file in "${test_files[@]}"; do
    local test_name
    test_name="$(basename "$test_file")"

    if [[ ! -x "$test_file" ]]; then
      chmod +x "$test_file"
    fi

    printf "  Running %-50s " "$test_name"

    local output
    local exit_code=0
    output=$("$test_file" 2>&1) || exit_code=$?

    if [[ "$exit_code" -eq 0 ]]; then
      printf "${GREEN}PASS${RESET}\n"
      suite_pass=$((suite_pass + 1))
    else
      printf "${RED}FAIL${RESET} (exit code: %d)\n" "$exit_code"
      suite_fail=$((suite_fail + 1))
      # Show last 5 lines of output on failure
      echo "$output" | tail -5 | while IFS= read -r line; do
        printf "    %s\n" "$line"
      done
    fi
  done

  TOTAL_PASS=$((TOTAL_PASS + suite_pass))
  TOTAL_FAIL=$((TOTAL_FAIL + suite_fail))

  local suite_status="PASS"
  if [[ "$suite_fail" -gt 0 ]]; then
    suite_status="FAIL"
  fi

  SUITE_RESULTS+=("$suite_name|$suite_pass|$suite_fail|$suite_skip|$suite_status")
  printf "  ${BOLD}%s: %d passed, %d failed${RESET}\n" "$suite_name" "$suite_pass" "$suite_fail"
}

# --- Main ---
printf "${BOLD}Echelon — Test Runner${RESET}\n"
printf "Root: %s\n" "$ROOT"
printf "Time: %s\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Run suites in order: unit, integration, e2e
run_suite "Unit Tests" "$SCRIPT_DIR/unit"
run_suite "Integration Tests" "$SCRIPT_DIR/integration"
run_suite "E2E Tests" "$SCRIPT_DIR/e2e"

# --- Summary ---
printf "\n${BOLD}========== SUMMARY ==========${RESET}\n\n"
printf "%-25s %8s %8s %8s %10s\n" "Suite" "Passed" "Failed" "Skipped" "Status"
printf "%-25s %8s %8s %8s %10s\n" "-------------------------" "--------" "--------" "--------" "----------"

for result in "${SUITE_RESULTS[@]}"; do
  IFS='|' read -r name pass fail skip status <<< "$result"
  local_color="$GREEN"
  if [[ "$status" == "FAIL" ]]; then
    local_color="$RED"
  elif [[ "$status" == *"SKIPPED"* ]]; then
    local_color="$YELLOW"
  fi
  printf "%-25s %8d %8d %8d ${local_color}%10s${RESET}\n" "$name" "$pass" "$fail" "$skip" "$status"
done

printf "\n${BOLD}Total: %d passed, %d failed, %d skipped${RESET}\n" "$TOTAL_PASS" "$TOTAL_FAIL" "$TOTAL_SKIP"

if [[ "$TOTAL_FAIL" -gt 0 ]]; then
  printf "\n${RED}${BOLD}OVERALL: FAIL${RESET}\n"
  exit 1
else
  printf "\n${GREEN}${BOLD}OVERALL: PASS${RESET}\n"
  exit 0
fi
