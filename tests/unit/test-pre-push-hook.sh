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

  mkdir -p "$tmpdir/.githooks" "$tmpdir/tests" "$tmpdir/scripts"
  cp "$HOOK" "$tmpdir/.githooks/pre-push"
  chmod +x "$tmpdir/.githooks/pre-push"
  : > "$tmpdir/scripts/merge_verification.py"

  (
    cd "$tmpdir" || exit 1
    git init -q -b main
    git config user.email test@example.test
    git config user.name test
    git config core.hooksPath .githooks
    printf 'base\n' > base.txt
    git add base.txt
    git commit -qm base
    printf 'candidate\n' > candidate.txt
    git add candidate.txt
    git commit -qm candidate
    printf '.venv/\nbin/\ntests/reports/\nrunner.log\npython.log\nvenv-python.log\n' > .gitignore
    printf '%s\n' "$exit_code" > runner-exit
    cat > tests/run-all.sh <<'SCRIPT'
#!/usr/bin/env bash
printf 'runner invoked\n' > runner.log
exit "$(cat runner-exit)"
SCRIPT
    chmod +x tests/run-all.sh
    git add .githooks tests scripts runner-exit .gitignore
    git commit -qm hook-fixture
  )

  printf '%s\n' "$tmpdir"
}

run_hook() {
  local tmpdir="$1"
  local remote="$2"
  local refs="${3:-}"
  (
    cd "$tmpdir" || exit 1
    printf '%s\n' "$refs" | .githooks/pre-push "$remote" "git@example.com:org/repo.git"
  )
}

install_fake_python() {
  local tmpdir="$1"
  mkdir -p "$tmpdir/bin"
  cat > "$tmpdir/bin/python3" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PWD/python.log"
case " $* " in
  *" confirm-fast-forward "*) exit "${CONFIRM_EXIT:-1}" ;;
  *" run "*) exit "${RUN_EXIT:-0}" ;;
  *) exit 64 ;;
esac
SCRIPT
  chmod +x "$tmpdir/bin/python3"
}

install_fake_venv_python() {
  local tmpdir="$1"
  mkdir -p "$tmpdir/.venv/bin"
  cat > "$tmpdir/.venv/bin/python" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PWD/venv-python.log"
case " $* " in
  *" confirm-fast-forward "*) exit "${CONFIRM_EXIT:-1}" ;;
  *" run "*) exit "${RUN_EXIT:-0}" ;;
  *) exit 64 ;;
esac
SCRIPT
  chmod +x "$tmpdir/.venv/bin/python"
}

main_push_refs() {
  local tmpdir="$1"
  local base head
  base="$(git -C "$tmpdir" rev-parse HEAD~1)"
  head="$(git -C "$tmpdir" rev-parse HEAD)"
  printf 'refs/heads/main %s refs/heads/main %s' "$head" "$base"
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

  tmp_receipt="$(make_sandbox 7)"
  install_fake_python "$tmp_receipt"
  mkdir -p "$tmp_receipt/tests/reports/merge-verification"
  : > "$tmp_receipt/tests/reports/merge-verification/receipt.json"
  set +e
  receipt_output="$(PYTHON="$tmp_receipt/bin/python3" CONFIRM_EXIT=0 run_hook "$tmp_receipt" origin "$(main_push_refs "$tmp_receipt")" 2>&1)"
  receipt_rc=$?
  set -e
  assert "matching receipt skips the full test runner" "$(
    [[ "$receipt_rc" -eq 0 && ! -f "$tmp_receipt/runner.log" && -f "$tmp_receipt/python.log" ]] \
      && grep -q 'confirm-fast-forward' "$tmp_receipt/python.log" \
      && ok_result || fail_result "rc=$receipt_rc output=$receipt_output"
  )"
  rm -rf "$tmp_receipt"

  tmp_selected="$(make_sandbox 7)"
  install_fake_python "$tmp_selected"
  set +e
  selected_output="$(PYTHON="$tmp_selected/bin/python3" RUN_EXIT=0 run_hook "$tmp_selected" origin "$(main_push_refs "$tmp_selected")" 2>&1)"
  selected_rc=$?
  set -e
  assert "clean main fast-forward runs selected verification" "$(
    [[ "$selected_rc" -eq 0 && ! -f "$tmp_selected/runner.log" && -f "$tmp_selected/python.log" ]] \
      && grep -q ' run --repo ' "$tmp_selected/python.log" \
      && grep -q ' --base ' "$tmp_selected/python.log" \
      && ok_result || fail_result "rc=$selected_rc output=$selected_output"
  )"
  rm -rf "$tmp_selected"

  tmp_helper_error="$(make_sandbox 0)"
  install_fake_python "$tmp_helper_error"
  set +e
  helper_output="$(PYTHON="$tmp_helper_error/bin/python3" RUN_EXIT=2 run_hook "$tmp_helper_error" origin "$(main_push_refs "$tmp_helper_error")" 2>&1)"
  helper_rc=$?
  set -e
  assert "selector errors retain the full test fallback" "$(
    [[ "$helper_rc" -eq 0 && -f "$tmp_helper_error/runner.log" ]] \
      && ok_result || fail_result "rc=$helper_rc output=$helper_output"
  )"
  rm -rf "$tmp_helper_error"

  tmp_venv="$(make_sandbox 7)"
  install_fake_venv_python "$tmp_venv"
  set +e
  venv_output="$(RUN_EXIT=0 run_hook "$tmp_venv" origin "$(main_push_refs "$tmp_venv")" 2>&1)"
  venv_rc=$?
  set -e
  assert "selected verification uses the repository virtualenv" "$(
    [[ "$venv_rc" -eq 0 && ! -f "$tmp_venv/runner.log" && -f "$tmp_venv/venv-python.log" ]] \
      && grep -q ' run --repo ' "$tmp_venv/venv-python.log" \
      && ok_result || fail_result "rc=$venv_rc output=$venv_output"
  )"
  rm -rf "$tmp_venv"
fi

printf '\nResults: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
