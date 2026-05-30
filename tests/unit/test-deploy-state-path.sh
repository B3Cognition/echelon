#!/usr/bin/env bash
# Regression tests for deploy-state path resolution.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
EXT_SCRIPTS="$REPO_ROOT/extension/scripts/bash"
ROOT_SCRIPTS="$REPO_ROOT/scripts/bash"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s - %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
project="$tmpdir/project"
home="$tmpdir/home"
run_id="run-active"
yaml_parent="$(python3 -c "import os, yaml; print(os.path.dirname(os.path.dirname(yaml.__file__)))" 2>/dev/null || true)"

mkdir -p "$project/runs/$run_id" "$project/.specify/extensions" "$home"
printf '%s\n' "$run_id" > "$project/runs/.current"
ln -s "$REPO_ROOT/extension" "$project/.specify/extensions/echelon"

cat > "$project/echelon-config.yml" <<'YAML'
deploy:
  enabled: true
  type: cli
  health_check: "true"
  install_path: ""
YAML

(cd "$project" && git init -q)

HOME="$home" PYTHONPATH="$yaml_parent${PYTHONPATH:+:$PYTHONPATH}" \
  bash "$ROOT_SCRIPTS/deploy-init.sh" "$project" "$project/echelon-config.yml" >/dev/null

assert "deploy-init writes state into active runs/.current directory" "$(
  [[ -f "$project/runs/$run_id/deploy-state.json" ]] && ok_result || fail_result "missing active run deploy-state.json"
)"
assert "deploy-init does not create legacy .specify/squad deploy state when active run exists" "$(
  [[ ! -f "$project/.specify/squad/deploy-state.json" ]] && ok_result || fail_result "legacy deploy-state.json exists"
)"

status_output="$(cd "$project" && HOME="$home" bash "$EXT_SCRIPTS/deploy-status.sh" 2>&1)"
assert "deploy-status reads state from active run" "$(
  [[ "$status_output" == *"deploy status (cli)"* ]] && ok_result || fail_result "$status_output"
)"

validate_output="$(cd "$project" && HOME="$home" PYTHONPATH="$yaml_parent${PYTHONPATH:+:$PYTHONPATH}" \
  bash "$ROOT_SCRIPTS/validate-deploy.sh" "$project" 2>&1)"
assert "validate-deploy reads state from active run" "$(
  [[ "$validate_output" == *"deploy-state.json valid"* ]] && ok_result || fail_result "$validate_output"
)"

rm -rf "$tmpdir"

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
