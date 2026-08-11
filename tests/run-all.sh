#!/usr/bin/env bash
# T-40: Unified test runner — runs all unit, integration, e2e, kernel, contract,
# echelon-validation, shim, and benchmark tests.
# Reports per-suite results and overall summary.
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

# Resolve one interpreter that satisfies pyproject.toml and can run pytest.
python_supports_tests() {
  "$1" -c 'import sys, pytest; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

selected_python=""
if [[ -n "${PYTHON:-}" ]] && python_supports_tests "$PYTHON"; then
  selected_python="$PYTHON"
fi
if [[ -z "$selected_python" ]] && [[ -x "$ROOT/.venv/bin/python" ]] && \
   python_supports_tests "$ROOT/.venv/bin/python"; then
  selected_python="$ROOT/.venv/bin/python"
fi
if [[ -z "$selected_python" ]] && [[ -x "$HOME/.echelon/venv/bin/python" ]] && \
   python_supports_tests "$HOME/.echelon/venv/bin/python"; then
  selected_python="$HOME/.echelon/venv/bin/python"
fi
if [[ -z "$selected_python" ]]; then
  for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3.12 python3 python; do
    if { [[ -x "$candidate" ]] || command -v "$candidate" >/dev/null 2>&1; } && \
       python_supports_tests "$candidate"; then
      selected_python="$candidate"
      break
    fi
  done
fi
if [[ -z "$selected_python" ]]; then
  echo "ERROR: Python 3.11+ with pytest is required to run the Echelon test suite." >&2
  exit 1
fi
PYTHON="$selected_python"
export PYTHON
PATH="$(dirname "$PYTHON"):$PATH"
export PATH

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

    printf "  Running %-50s " "$test_name"

    local output
    local exit_code=0
    output=$(bash "$test_file" 2>&1) || exit_code=$?

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

run_pytest_suite() {
  local suite_name="$1"
  local suite_dir="$2"

  printf "\n${BOLD}========== %s ==========${RESET}\n" "$suite_name"

  if [[ ! -d "$suite_dir" ]]; then
    printf "${YELLOW}SKIP: Directory not found: %s${RESET}\n" "$suite_dir"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no directory)")
    return
  fi

  if [[ -z "$PYTHON" ]]; then
    printf "${YELLOW}SKIP: No Python interpreter with pytest found${RESET}\n"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no pytest)")
    return
  fi

  local python_test_file
  python_test_file=$(find "$suite_dir" -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit)
  if [[ -z "$python_test_file" ]]; then
    printf "${YELLOW}SKIP: No Python test files found in %s${RESET}\n" "$suite_dir"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no tests)")
    return
  fi

  local output exit_code=0
  output=$(cd "$ROOT" && "$PYTHON" -m pytest "$suite_dir" -q --tb=short 2>&1) || exit_code=$?

  # Parse pytest summary line: "X passed, Y failed" or "X passed"
  local suite_pass=0 suite_fail=0
  suite_pass=$(echo "$output" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
  suite_fail=$(echo "$output" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)
  suite_pass=${suite_pass:-0}
  suite_fail=${suite_fail:-0}

  TOTAL_PASS=$((TOTAL_PASS + suite_pass))
  TOTAL_FAIL=$((TOTAL_FAIL + suite_fail))

  # Print pytest summary line and any failure details
  local summary_line
  summary_line=$(echo "$output" | grep -E '^(FAILED|ERROR|[0-9]+ (passed|failed))' || true)
  [[ -n "$summary_line" ]] && printf "  %s\n" "$summary_line"

  local suite_status="PASS"
  if [[ "$exit_code" -ne 0 ]]; then
    suite_status="FAIL"
    # Show short failure output (last 20 lines covers most tb=short summaries)
    printf "%s\n" "$output" | tail -20 | while IFS= read -r line; do
      printf "    %s\n" "$line"
    done
  fi

  SUITE_RESULTS+=("$suite_name|$suite_pass|$suite_fail|0|$suite_status")
  printf "  ${BOLD}%s: %d passed, %d failed${RESET}\n" "$suite_name" "$suite_pass" "$suite_fail"
}

run_pytest_target() {
  local suite_name="$1"
  shift

  printf "\n${BOLD}========== %s ==========${RESET}\n" "$suite_name"

  if [[ -z "$PYTHON" ]]; then
    printf "${YELLOW}SKIP: No Python interpreter with pytest found${RESET}\n"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no pytest)")
    return
  fi

  local output exit_code=0
  output=$(cd "$ROOT" && "$PYTHON" -m pytest "$@" -q --tb=short 2>&1) || exit_code=$?

  local suite_pass=0 suite_fail=0
  suite_pass=$(echo "$output" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
  suite_fail=$(echo "$output" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)
  suite_pass=${suite_pass:-0}
  suite_fail=${suite_fail:-0}

  TOTAL_PASS=$((TOTAL_PASS + suite_pass))
  TOTAL_FAIL=$((TOTAL_FAIL + suite_fail))

  local summary_line
  summary_line=$(echo "$output" | grep -E '^(FAILED|ERROR|[0-9]+ (passed|failed))' || true)
  [[ -n "$summary_line" ]] && printf "  %s\n" "$summary_line"

  local suite_status="PASS"
  if [[ "$exit_code" -ne 0 ]]; then
    suite_status="FAIL"
    printf "%s\n" "$output" | tail -20 | while IFS= read -r line; do
      printf "    %s\n" "$line"
    done
  fi

  SUITE_RESULTS+=("$suite_name|$suite_pass|$suite_fail|0|$suite_status")
  printf "  ${BOLD}%s: %d passed, %d failed${RESET}\n" "$suite_name" "$suite_pass" "$suite_fail"
}

run_bench_suite() {
  local suite_name="$1"
  local suite_dir="$2"
  local suite_pass=0
  local suite_fail=0

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
  done < <(find "$suite_dir" -maxdepth 1 -name 'bench-*.sh' -type f -print0 | sort -z)

  if [[ ${#test_files[@]} -eq 0 ]]; then
    printf "${YELLOW}SKIP: No bench files found in %s${RESET}\n" "$suite_dir"
    SUITE_RESULTS+=("$suite_name|0|0|0|SKIPPED (no tests)")
    return
  fi

  for test_file in "${test_files[@]}"; do
    local test_name
    test_name="$(basename "$test_file")"
    printf "  Running %-50s " "$test_name"
    local output exit_code=0
    output=$(bash "$test_file" 2>&1) || exit_code=$?
    if [[ "$exit_code" -eq 0 ]]; then
      printf "${GREEN}PASS${RESET}\n"
      suite_pass=$((suite_pass + 1))
    else
      printf "${RED}FAIL${RESET} (exit code: %d)\n" "$exit_code"
      suite_fail=$((suite_fail + 1))
      echo "$output" | tail -5 | while IFS= read -r line; do printf "    %s\n" "$line"; done
    fi
  done

  TOTAL_PASS=$((TOTAL_PASS + suite_pass))
  TOTAL_FAIL=$((TOTAL_FAIL + suite_fail))
  local suite_status="PASS"
  [[ "$suite_fail" -gt 0 ]] && suite_status="FAIL"
  SUITE_RESULTS+=("$suite_name|$suite_pass|$suite_fail|0|$suite_status")
  printf "  ${BOLD}%s: %d passed, %d failed${RESET}\n" "$suite_name" "$suite_pass" "$suite_fail"
}

run_single_test() {
  local suite_name="$1"
  local test_file="$2"

  printf "\n${BOLD}========== %s ==========${RESET}\n" "$suite_name"

  if [[ ! -f "$test_file" ]]; then
    printf "${YELLOW}SKIP: File not found: %s${RESET}\n" "$test_file"
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    SUITE_RESULTS+=("$suite_name|0|0|1|SKIPPED (no file)")
    return
  fi

  printf "  Running %-50s " "$(basename "$test_file")"
  local output exit_code=0
  output=$(bash "$test_file" 2>&1) || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    printf "${GREEN}PASS${RESET}\n"
    TOTAL_PASS=$((TOTAL_PASS + 1))
    SUITE_RESULTS+=("$suite_name|1|0|0|PASS")
  else
    printf "${RED}FAIL${RESET} (exit code: %d)\n" "$exit_code"
    echo "$output" | tail -5 | while IFS= read -r line; do printf "    %s\n" "$line"; done
    TOTAL_FAIL=$((TOTAL_FAIL + 1))
    SUITE_RESULTS+=("$suite_name|0|1|0|FAIL")
  fi
}

# --- Main ---
printf "${BOLD}Echelon — Test Runner${RESET}\n"
printf "Root: %s\n" "$ROOT"
printf "Time: %s\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf "Python: %s (%s)\n" "$PYTHON" "$("$PYTHON" -c 'import platform; print(platform.python_version())')"

# Bash suites
run_suite "Unit Tests" "$SCRIPT_DIR/unit"
run_suite "Integration Tests" "$SCRIPT_DIR/integration"
run_suite "Integration/RE Tests" "$SCRIPT_DIR/integration/re"
run_suite "E2E Tests" "$SCRIPT_DIR/e2e"

# Migrated deterministic contract tests
run_pytest_target "EGR-022 Static Contracts" \
  "$SCRIPT_DIR/unit/test_no_new_deps_pytest.py" \
  "$SCRIPT_DIR/unit/test_registry_sync_pytest.py" \
  "$SCRIPT_DIR/unit/test_language_rules_pytest.py" \
  "$SCRIPT_DIR/unit/test_static_contracts_pytest.py"

# Pytest suites
run_pytest_suite "Kernel Tests" "$SCRIPT_DIR/kernel"
run_pytest_suite "Contract Tests" "$SCRIPT_DIR/contract"
run_pytest_suite "Echelon Validation" "$SCRIPT_DIR/echelon-validation"

# Benchmarks
run_bench_suite "Benchmarks" "$SCRIPT_DIR/benchmarks"

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
