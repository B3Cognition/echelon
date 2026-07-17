#!/usr/bin/env bash
# Unit tests for the local pre-push test gate.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/.githooks/pre-push"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass + 1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail + 1))
    printf 'FAIL: %s - %s\n' "$desc" "${result#FAIL:}"
  fi
}

ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

make_sandbox() {
  local exit_code="$1"
  local tmpdir
  tmpdir="$(mktemp -d)"

  mkdir -p "$tmpdir/.githooks" "$tmpdir/tests"
  cp "$HOOK" "$tmpdir/.githooks/pre-push"
  chmod +x "$tmpdir/.githooks/pre-push"

  (
    cd "$tmpdir" || exit 1
    git init -q
    git config core.hooksPath .githooks
    printf '%s\n' "$exit_code" > runner-exit
    cat > tests/run-all.sh <<'SCRIPT'
#!/usr/bin/env bash
printf 'runner invoked\n' > runner.log
exit "$(cat runner-exit)"
SCRIPT
    chmod +x tests/run-all.sh
  )

  printf '%s\n' "$tmpdir"
}

run_hook() {
  local tmpdir="$1"
  local remote="$2"
  (
    cd "$tmpdir" || exit 1
    .githooks/pre-push "$remote" "git@example.com:org/repo.git" </dev/null
  )
}

assert "pre-push hook exists" "$(
  [[ -f "$HOOK" ]] && ok_result || fail_result "$HOOK not found"
)"

assert "pre-push hook is executable" "$(
  [[ -x "$HOOK" ]] && ok_result || fail_result "$HOOK is not executable"
)"

if [[ -f "$HOOK" ]]; then
  tmp_fail="$(make_sandbox 7)"
  set +e
  fail_output="$(run_hook "$tmp_fail" origin 2>&1)"
  fail_rc=$?
  set -e
  assert "origin push invokes full test runner" "$(
    [[ -f "$tmp_fail/runner.log" ]] && ok_result || fail_result "runner was not invoked; output=$fail_output"
  )"
  assert "origin push is blocked when tests fail" "$(
    [[ "$fail_rc" -ne 0 ]] && ok_result || fail_result "hook exited $fail_rc"
  )"
  rm -rf "$tmp_fail"

  tmp_pass="$(make_sandbox 0)"
  set +e
  pass_output="$(run_hook "$tmp_pass" origin 2>&1)"
  pass_rc=$?
  set -e
  assert "origin push is allowed when tests pass" "$(
    [[ "$pass_rc" -eq 0 ]] && ok_result || fail_result "hook exited $pass_rc; output=$pass_output"
  )"
  rm -rf "$tmp_pass"

  tmp_skip="$(make_sandbox 7)"
  set +e
  skip_output="$(run_hook "$tmp_skip" upstream 2>&1)"
  skip_rc=$?
  set -e
  assert "non-origin push skips local test gate" "$(
    [[ "$skip_rc" -eq 0 && ! -f "$tmp_skip/runner.log" ]] \
      && ok_result || fail_result "rc=$skip_rc output=$skip_output"
  )"
  rm -rf "$tmp_skip"
fi

printf '\nResults: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
