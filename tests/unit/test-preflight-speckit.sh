#!/usr/bin/env bash
# T021: Unit tests — Story 001a Detection + Classification
# Tests preflight-speckit.sh exit codes, error codes, and stdout format.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"
MOCKS="$REPO_ROOT/tests/mocks"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"

pass=0
fail=0

# Helpers -------------------------------------------------------------------

ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}

# create_wrapper <tmpdir> <mode> [timeout_seconds]: creates a +x wrapper for spec-kit mock
# in tmpdir and sets the mode in spec-kit.conf. Returns wrapper dir path on stdout.
create_wrapper() {
  local tmpdir="$1"
  local mode="$2"
  local timeout_seconds="${3:-3}"
  printf 'mode=%s\ntimeout_seconds=%s\n' "$mode" "$timeout_seconds" > "$MOCKS/spec-kit.conf"
  printf '#!/usr/bin/env bash\nexec bash "%s" "$@"\n' "$MOCKS/spec-kit" > "$tmpdir/spec-kit"
  chmod +x "$tmpdir/spec-kit"
}

# run_preflight_rc <wrapper_dir>: runs preflight (stdout/stderr suppressed), echoes exit code only
run_preflight_rc() {
  local _rc
  set +e
  PATH="$1:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit >/dev/null 2>&1
  _rc=$?
  set -e
  echo "$_rc"
}

reset_error_log() {
  mkdir -p "$(dirname "$ERROR_LOG")"
  if [[ -f "$ERROR_LOG" ]]; then
    cp "$ERROR_LOG" "${ERROR_LOG}.test_backup.$$"
  fi
  : > "$ERROR_LOG"
}

restore_conf_and_log() {
  if [[ -n "${ORIG_CONF:-}" ]]; then
    printf '%s\n' "$ORIG_CONF" > "$MOCKS/spec-kit.conf"
  fi
  if [[ -f "${ERROR_LOG}.test_backup.$$" ]]; then
    mv "${ERROR_LOG}.test_backup.$$" "$ERROR_LOG"
  else
    rm -f "$ERROR_LOG"
  fi
  rm -rf "${TMPWRAP:-}"
}
trap restore_conf_and_log EXIT

ORIG_CONF=""
[[ -f "$MOCKS/spec-kit.conf" ]] && ORIG_CONF="$(cat "$MOCKS/spec-kit.conf")"

TMPWRAP="$(mktemp -d)"

# TEST-001a-1: available mode → exit 0, stdout DEPENDENCY_SPECKIT_AVAILABLE ----------------

reset_error_log
create_wrapper "$TMPWRAP" available
rc="$(run_preflight_rc "$TMPWRAP")"
assert "TEST-001a-1: available exits 0" "$(
  [[ "$rc" == "0" ]] && ok_result || fail_result "expected exit 0, got $rc"
)"

stdout_val="$(PATH="$TMPWRAP:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit 2>/dev/null || true)"
assert "TEST-001a-1: available stdout DEPENDENCY_SPECKIT_AVAILABLE" "$(
  [[ "$stdout_val" == DEPENDENCY_SPECKIT_AVAILABLE:* ]] && ok_result || fail_result "stdout='$stdout_val'"
)"

assert "TEST-001a-1: no error.log entry on success" "$(
  grep -q 'DEPENDENCY_SPECKIT' "$ERROR_LOG" 2>/dev/null \
    && fail_result "found DEPENDENCY_SPECKIT in error.log" \
    || ok_result
)"

# Timing check
start_ms="$(python3 -c 'import time; print(int(time.time()*1000))')"
PATH="$TMPWRAP:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit >/dev/null 2>&1 || true
end_ms="$(python3 -c 'import time; print(int(time.time()*1000))')"
elapsed_ms=$((end_ms - start_ms))
assert "TEST-001a-1: available completes < 2000ms" "$(
  [[ "$elapsed_ms" -lt 2000 ]] && ok_result || fail_result "elapsed=${elapsed_ms}ms"
)"

# TEST-001a-2: unavailable (nonexistent command) → exit 1, DEPENDENCY_SPECKIT_UNAVAILABLE ---

reset_error_log
set +e
bash "$SCRIPTS/preflight-speckit.sh" --cmd /nonexistent/speckit-not-found-xyz >/dev/null 2>&1
rc=$?
set -e
assert "TEST-001a-2: missing cmd exits 1" "$(
  [[ "$rc" == "1" ]] && ok_result || fail_result "expected exit 1, got $rc"
)"
assert "TEST-001a-2: error.log has DEPENDENCY_SPECKIT_UNAVAILABLE" "$(
  grep -q 'DEPENDENCY_SPECKIT_UNAVAILABLE' "$ERROR_LOG" 2>/dev/null && ok_result || fail_result "not in error.log"
)"

# TEST-001a-6 (timeout path): mock-timeout → exit 2, DEPENDENCY_SPECKIT_TIMEOUT ------------

reset_error_log
create_wrapper "$TMPWRAP" timeout 4
rc="$(run_preflight_rc "$TMPWRAP")"
assert "TEST-001a-6: timeout exits 2" "$(
  [[ "$rc" == "2" ]] && ok_result || fail_result "expected exit 2, got $rc"
)"
assert "TEST-001a-6: error.log has DEPENDENCY_SPECKIT_TIMEOUT" "$(
  grep -q 'DEPENDENCY_SPECKIT_TIMEOUT' "$ERROR_LOG" 2>/dev/null && ok_result || fail_result "not in error.log"
)"

# TEST-001a-4 (negative): available → no DEPENDENCY error in error.log ---------------------

reset_error_log
create_wrapper "$TMPWRAP" available
PATH="$TMPWRAP:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit >/dev/null 2>&1 || true
assert "TEST-001a-4: available mode emits no DEPENDENCY error in error.log" "$(
  grep -qE 'DEPENDENCY_SPECKIT_UNAVAILABLE|DEPENDENCY_SPECKIT_TIMEOUT|DEPENDENCY_SPECKIT_INCOMPATIBLE' \
    "$ERROR_LOG" 2>/dev/null \
    && fail_result "found unexpected DEPENDENCY error in error.log" \
    || ok_result
)"

# TEST-001a-5: distinct error codes for timeout vs unavailable ---------------------------

reset_error_log
create_wrapper "$TMPWRAP" timeout 4
PATH="$TMPWRAP:$PATH" bash "$SCRIPTS/preflight-speckit.sh" --cmd spec-kit >/dev/null 2>&1 || true
timeout_code="$(grep 'DEPENDENCY_SPECKIT' "$ERROR_LOG" 2>/dev/null | head -1 || true)"

reset_error_log
bash "$SCRIPTS/preflight-speckit.sh" --cmd /nonexistent/xyz-not-found >/dev/null 2>&1 || true
unavail_code="$(grep 'DEPENDENCY_SPECKIT' "$ERROR_LOG" 2>/dev/null | head -1 || true)"

assert "TEST-001a-5: timeout and unavailable have distinct error codes" "$(
  [[ "$timeout_code" != "$unavail_code" && -n "$timeout_code" && -n "$unavail_code" ]] \
    && ok_result || fail_result "timeout='$timeout_code' unavail='$unavail_code'"
)"

# TEST-001a-3: incompatible mode → exit 3 ---------------------------------------------------

reset_error_log
create_wrapper "$TMPWRAP" incompatible
rc="$(run_preflight_rc "$TMPWRAP")"
assert "TEST-001a-3: incompatible exits 3" "$(
  [[ "$rc" == "3" ]] && ok_result || fail_result "expected exit 3, got $rc"
)"

# Summary -------------------------------------------------------------------

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
